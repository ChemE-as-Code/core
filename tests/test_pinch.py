"""Pinch analysis (domains/process/heat_integration/pinch.py), new in core: LLM4ChemE had none.

The four-stream example is Kemp, Pinch Analysis and Process Integration (2nd ed.), with the duties
in kW instead of MW: minimum hot utility 20, cold utility 60, pinch at 90/80 °C (shifted 85 °C).
The latent-heat and composite-curve cases are constructed so that the answer follows by hand
(the arithmetic is in each test); they are not data.
"""

import pytest

from chemeascode.domains.process.heat_integration.pinch import (
    PinchStream,
    Segment,
    minimum_approach,
    pinch_analysis,
)

C = 273.15  # the example is in °C; the function takes K


def kemp():
    return [
        PinchStream(170 + C, 60 + C, 3.0, "H1"),
        PinchStream(150 + C, 30 + C, 1.5, "H2"),
        PinchStream(20 + C, 135 + C, 2.0, "C1"),
        PinchStream(80 + C, 140 + C, 4.0, "C2"),
    ]


def test_four_stream_example():
    result = pinch_analysis(kemp(), dt_min=10)
    assert result.min_hot_utility == pytest.approx(20.0)
    assert result.min_cold_utility == pytest.approx(60.0)
    assert result.pinch_shifted_temperature == pytest.approx(85 + C)
    assert result.pinch_hot_temperature == pytest.approx(90 + C)
    assert result.pinch_cold_temperature == pytest.approx(80 + C)
    assert not result.threshold
    assert [round(i.delta_h, 6) for i in result.intervals] == [60, 2.5, -82.5, 75, -15]
    assert [round(q, 6) for _, q in result.grand_composite_curve] == [20, 80, 82.5, 0, 75, 60]
    assert result.units["heat"] == "kW"
    # a target, not a network
    assert result.basis == "targets" and "not a synthesized" in result.scope


def test_utilities_close_the_energy_balance():
    streams = kemp()
    result = pinch_analysis(streams, dt_min=20)
    hot = sum(s.duty for s in streams if s.kind == "hot")
    cold = sum(s.duty for s in streams if s.kind == "cold")
    assert result.min_hot_utility - result.min_cold_utility == pytest.approx(cold - hot)
    assert result.min_hot_utility > pinch_analysis(streams, dt_min=10).min_hot_utility


def test_threshold_problem_has_no_pinch():
    streams = [
        PinchStream(150 + C, 60 + C, 2.0),
        PinchStream(90 + C, 60 + C, 8.0),
        PinchStream(20 + C, 125 + C, 2.5),
        PinchStream(25 + C, 100 + C, 3.0),
    ]
    result = pinch_analysis(streams, dt_min=10)
    assert result.min_hot_utility == pytest.approx(67.5)
    assert result.min_cold_utility == pytest.approx(0.0, abs=1e-9)
    assert result.threshold and result.pinch_hot_temperature is None


@pytest.mark.parametrize(
    ("streams", "dt_min", "message"),
    [
        ([PinchStream(400, 300, 1.0)], 10, "at least 2"),
        ([PinchStream(400, 300, 0.0), PinchStream(300, 400, 1.0)], 10, "greater than 0"),
        ([PinchStream(400, 400, 1.0), PinchStream(300, 400, 1.0)], 10, "must differ"),
        ([PinchStream(400, 300, 1.0), PinchStream(300, 400, 1.0)], -1, "negative"),
    ],
)
def test_invalid_input_is_refused(streams, dt_min, message):
    with pytest.raises(ValueError, match=message):
        pinch_analysis(streams, dt_min)


def test_constant_cp_stream_equals_one_sensible_segment():
    streams = kemp()
    as_segments = [
        PinchStream.piecewise(
            [Segment.sensible(s.supply_temperature, s.target_temperature, s.heat_capacity_flow)],
            s.name,
        )
        for s in streams
    ]
    a, b = pinch_analysis(streams, 10), pinch_analysis(as_segments, 10)
    assert (a.min_hot_utility, a.min_cold_utility) == pytest.approx(
        (b.min_hot_utility, b.min_cold_utility)
    )
    assert a.pinch_shifted_temperature == pytest.approx(b.pinch_shifted_temperature)


def test_boiling_stream_enters_the_cascade_at_its_temperature():
    """A cold stream boiling at 390 K (50 kW) against a hot stream 420 -> 350 K at 1 kW/K
    (70 kW), dt_min 10 K. Shifted: the boiling at 395 K, the hot stream 415 -> 345 K. Above
    395 K the hot stream gives 20 kW; the boiling needs 50, so 30 kW hot utility; below 395 K
    the hot stream's remaining 50 kW go to cold utility. Pinch at 400 K hot / 390 K cold."""
    boiling = PinchStream.piecewise([Segment.latent(390, 50)], "C1", side="cold")
    result = pinch_analysis([boiling, PinchStream(420, 350, 1.0, "H1")], dt_min=10)
    assert result.min_hot_utility == pytest.approx(30.0)
    assert result.min_cold_utility == pytest.approx(50.0)
    assert result.pinch_hot_temperature == pytest.approx(400.0)
    assert result.pinch_cold_temperature == pytest.approx(390.0)
    latent = [i for i in result.intervals if i.isothermal]
    assert len(latent) == 1 and latent[0].high == latent[0].low == pytest.approx(395.0)
    assert latent[0].delta_h == pytest.approx(-50.0) and latent[0].streams == [0]
    # the isothermal load is a horizontal step of the grand composite curve
    assert result.grand_composite_curve == pytest.approx(
        [(415.0, 30.0), (395.0, 50.0), (395.0, 0.0), (345.0, 50.0)]
    )


def test_condensing_stream_and_threshold():
    """Steam-like condensing at 400 K (100 kW) heating 300 -> 380 K at 1 kW/K (80 kW): the
    condensing load covers the cold stream, 20 kW are left for cold utility, no pinch."""
    condensing = PinchStream.piecewise([Segment.latent(400, 100)], "H1", side="hot")
    result = pinch_analysis([condensing, PinchStream(300, 380, 1.0, "C1")], dt_min=10)
    assert result.min_hot_utility == pytest.approx(0.0, abs=1e-9)
    assert result.min_cold_utility == pytest.approx(20.0)
    assert result.threshold


def test_piecewise_stream_with_sensible_and_latent_parts():
    """Water-like cold stream: liquid 300 -> 350 K at 2 kW/K (100 kW), boiling at 350 K
    (200 kW), vapour 350 -> 400 K at 1 kW/K (50 kW); heated by 500 -> 340 K at 2.5 kW/K
    (400 kW), dt_min 10 K. Shifted cold 305, 355 (boiling), 405; hot 495 -> 335. Cascade:
    495-405 +225; 405-355 +125-50 = +75 (300); boiling -200 (100); 355-335 +50-40 = +10
    (110); 335-305 -60 (50). No deficit: threshold, 50 kW cold utility."""
    water = PinchStream.piecewise(
        [
            Segment.sensible(300, 350, 2.0),
            Segment.latent(350, 200),
            Segment.sensible(350, 400, 1.0),
        ],
        "C1",
    )
    assert water.kind == "cold" and water.duty == pytest.approx(350.0)
    result = pinch_analysis([water, PinchStream(500, 340, 2.5, "H1")], dt_min=10)
    assert result.min_hot_utility == pytest.approx(0.0, abs=1e-9)
    assert result.min_cold_utility == pytest.approx(50.0)
    assert [round(q, 6) for _, q in result.grand_composite_curve] == [0, 225, 300, 100, 110, 50]


@pytest.mark.parametrize(
    ("streams", "message"),
    [
        ([PinchStream.piecewise([Segment.latent(400, 10)]), PinchStream(300, 350, 1.0)], "side"),
        (
            [
                PinchStream.piecewise([Segment(400, 350, 10), Segment(340, 300, 10)]),
                PinchStream(300, 350, 1.0),
            ],
            "does not start",
        ),
        (
            [
                PinchStream.piecewise([Segment(400, 350, 10), Segment(350, 360, 10)], side="hot"),
                PinchStream(300, 350, 1.0),
            ],
            "other way",
        ),
        ([PinchStream.piecewise([Segment(400, 350, 0)]), PinchStream(300, 350, 1.0)], "duty"),
    ],
)
def test_invalid_segments_are_refused(streams, message):
    with pytest.raises(ValueError, match=message):
        pinch_analysis(streams, 10)


def test_minimum_approach_of_constant_cp_exchanger_is_terminal():
    """Hot 400 -> 350 K at 2 kW/K, cold 300 -> 380 K at 1.25 kW/K (100 kW each): terminal
    differences 400 - 380 = 20 K and 350 - 300 = 50 K."""
    found = minimum_approach([PinchStream(400, 350, 2.0), PinchStream(300, 380, 1.25)])
    assert found.minimum == pytest.approx(20.0)
    assert (found.hot_temperature, found.cold_temperature) == pytest.approx((400.0, 380.0))
    assert not found.crossed


def test_minimum_approach_finds_internal_pinch_of_boiling_stream():
    """Cold: 300 -> 340 K at 0.5 kW/K (20 kW), boiling at 340 K (80 kW); hot 420 -> 320 K at
    1 kW/K (100 kW). The terminal differences are 80 K and 20 K, yet 20 kW from the cold end
    the hot stream is at 340 K where the cold one starts boiling: 0 K inside."""
    cold = PinchStream.piecewise([Segment.sensible(300, 340, 0.5), Segment.latent(340, 80)])
    found = minimum_approach([PinchStream(420, 320, 1.0), cold])
    assert found.minimum == pytest.approx(0.0, abs=1e-9)
    assert found.heat == pytest.approx(20.0)
    hotter = minimum_approach([PinchStream(425, 325, 1.0), cold])
    assert hotter.minimum == pytest.approx(5.0)


def test_minimum_approach_condenser_and_cross():
    """Condensing at 373.15 K (100 kW) against cooling water 293 -> 303 K (10 kW/K): 70.15 K.
    Hot 400 -> 350 K at 2 kW/K against cold 340 -> 410 K at 100/70 kW/K: crossed at the hot
    end (400 - 410 = -10 K)."""
    condenser = PinchStream.piecewise([Segment.latent(373.15, 100)], side="hot")
    found = minimum_approach([condenser, PinchStream(293, 303, 10.0)])
    assert found.minimum == pytest.approx(70.15)
    crossed = minimum_approach([PinchStream(400, 350, 2.0), PinchStream(340, 410, 100 / 70)])
    assert crossed.crossed and crossed.minimum == pytest.approx(-10.0)
    with pytest.raises(ValueError, match="hot and a cold"):
        minimum_approach([PinchStream(400, 350, 2.0), PinchStream(390, 300, 1.0)])


# -- textbook and hand-checked cases for the plant targets (cheme process pinch) -------------


def smith():
    """Smith, Chemical Process Design and Integration (Wiley, 2005), chapter 16, the
    four-stream example (duties in MW there, kW/K and kW here): H1 250 -> 40 degC at 0.15,
    H2 200 -> 80 degC at 0.25, C3 20 -> 180 degC at 0.20, C4 140 -> 230 degC at 0.30. At
    dTmin 10 K the book gives minimum hot utility 7.5, cold utility 10.0 and the pinch at
    150 degC (hot) / 140 degC (cold). Checked against the stream table and problem-table
    cascade reproduced in the University of Oklahoma ChE design course notes "Pinch and minimum
    utility usage" (ou.edu/class/che-design/a-design/Minimum Utility.pdf): the same streams,
    7.5 MW heating and 10.0 MW cooling."""
    return [
        PinchStream(250 + C, 40 + C, 0.15, "H1"),
        PinchStream(200 + C, 80 + C, 0.25, "H2"),
        PinchStream(20 + C, 180 + C, 0.20, "C3"),
        PinchStream(140 + C, 230 + C, 0.30, "C4"),
    ]


def test_four_stream_textbook_example():
    result = pinch_analysis(smith(), dt_min=10)
    assert result.min_hot_utility == pytest.approx(7.5)
    assert result.min_cold_utility == pytest.approx(10.0)
    assert result.pinch_hot_temperature == pytest.approx(150 + C)
    assert result.pinch_cold_temperature == pytest.approx(140 + C)
    assert result.pinch_shifted_temperature == pytest.approx(145 + C)


def test_threshold_approach_turns_into_a_pinch():
    """Hot 200 -> 100 degC at 1 kW/K (100 kW), cold 50 -> 150 degC at 0.8 kW/K (80 kW),
    constructed by hand. With no utility at the top the composites approach closest at the hot
    end, 200 - 150 = 50 K, so up to dTmin 50 K the problem is a threshold problem: no hot
    utility, 100 - 80 = 20 kW of cold utility, no pinch (the threshold behaviour of Kemp, Pinch
    Analysis and Process Integration, 2nd ed., and Ray and Das, Process Equipment and Plant
    Design, section 5.7). Beyond it the cold end above 200 - dTmin needs hot utility,
    0.8 x (dTmin - 50): at 60 K 8 kW hot, 28 kW cold, pinch at the hot supply, 200 / 140 degC."""
    streams = [PinchStream(200 + C, 100 + C, 1.0, "H1"), PinchStream(50 + C, 150 + C, 0.8, "C1")]
    for dt in (10, 50):
        below = pinch_analysis(streams, dt_min=dt)
        assert below.threshold and below.pinch_hot_temperature is None
        assert below.min_hot_utility == pytest.approx(0.0, abs=1e-9)
        assert below.min_cold_utility == pytest.approx(20.0)
    above = pinch_analysis(streams, dt_min=60)
    assert not above.threshold
    assert (above.min_hot_utility, above.min_cold_utility) == pytest.approx((8.0, 28.0))
    assert above.pinch_hot_temperature == pytest.approx(200 + C)
    assert above.pinch_cold_temperature == pytest.approx(140 + C)


def test_latent_loads_of_a_column_against_a_process_stream():
    """A column as the extraction gives it (cheme process pinch): its condenser an isothermal
    hot load of 300 kW at 360 K, its reboiler an isothermal cold load of 400 kW at 420 K, and
    a hot process stream 500 -> 380 K at 2 kW/K (240 kW), dTmin 10 K; constructed by hand.
    Shifted: hot stream 495 -> 375, reboiler at 425, condenser at 355. Cascade: 495-425 gives
    140 kW, the reboiler takes 400 (-260), 425-375 gives 100 (-160), the condenser gives 300
    (+140). Most negative -260: 260 kW hot utility, 400 kW cold utility, pinch at the
    reboiler (shifted 425 K: 430 K hot, 420 K cold): the reboiler's latent load sits at the
    pinch, the condenser's lies wholly below it."""
    condenser = PinchStream.piecewise([Segment.latent(360, 300)], "condenser", side="hot")
    reboiler = PinchStream.piecewise([Segment.latent(420, 400)], "reboiler", side="cold")
    result = pinch_analysis([condenser, reboiler, PinchStream(500, 380, 2.0, "H1")], dt_min=10)
    assert result.min_hot_utility == pytest.approx(260.0)
    assert result.min_cold_utility == pytest.approx(400.0)
    assert result.pinch_shifted_temperature == pytest.approx(425.0)
    assert (result.pinch_hot_temperature, result.pinch_cold_temperature) == pytest.approx(
        (430.0, 420.0)
    )
