# Shapes in the reference shape catalogue

Reuse these by id (`<References objects="#ShapeN" property="Shape"/>` in a ShapeUsage). They are in `empty-sheet.xml` already.

| id | name | used by |
|---|---|---|
| Shape21 | CENTRIFUGAL_PUMP_SHAPE | CentrifugalPump1 |
| Shape22 | RECIPROCATING_PUMP_SHAPE | ReciprocatingPump1 |
| Shape23 | VESSEL_WITH_DISHED_HEADS_SHAPE | Tank1 |
| Shape18 | PLATE_TYPE_HEAT_EXCHANGER_SHAPE | PlateHeatExchanger1 |
| Shape20 | FLOATING_HEAD_TUBE_BUNDLE_HEAT_EXCHANGER_SHAPE | TubularHeatExchanger1 |
| Shape24 | MANHOLE_SHAPE | Nozzle19 |
| Shape19 | NOZZLE_SHAPE | Nozzle1, Nozzle10, Nozzle11, Nozzle12, Nozzle13, Nozzle14, Nozzle15, Nozzle16, Nozzle17, Nozzle18, Nozzle2, Nozzle3, Nozzle4, Nozzle5, Nozzle6, Nozzle7, Nozzle8, Nozzle9 |
| Shape8 | BALL_VALVE_SHAPE | BallValve1, BallValve2, BallValve3, BallValve4, BallValve5 |
| Shape3 | GLOBE_VALVE_SHAPE | GlobeValve1, GlobeValve2, GlobeValve3 |
| Shape6 | SWING_CHECK_VALVE_SHAPE | SwingCheckValve1 |
| Shape5 | BUTTERFLY_VALVE_SHAPE | ButterflyValve1 |
| Shape9 | ANGLE_SAFETY_VALVE_SPRING_LOADED_SHAPE | SpringLoadedGlobeSafetyValve1 |
| Shape13 | BLIND_COVER_SHAPE | BlindFlange1, BlindFlange2 |
| Shape7 | REDUCER_GENERAL_SHAPE | PipeReducer1 |
| Shape12 | T_TYPE_CONNECTION_SHAPE | PipeTee1, PipeTee2, PipeTee3, PipeTee4, PipeTee5 |
| Shape15 | PIPING_INSULATED_SHAPE | PipingNetworkSegment19 |
| Shape11 | SLOPE_SHAPE | PipingNetworkSegment8 |
| Shape1 | CONTROLLED_ACTUATOR_SHAPE | ControlledActuator1, ControlledActuator2, ControlledActuator3 |
| Shape2 | ARROW_FOR_INLET_OF_ESSENTIAL_SUBSTANCES_SHAPE | FlowInPipeOffPageConnector1 |
| Shape14 | ARROW_FOR_OUTLET_OF_ESSENTIAL_SUBSTANCES_SHAPE | FlowOutPipeOffPageConnector1 |
| Shape4 | DIRECTION_OF_FLOW_SHAPE_FOR_PRIMARY_SEGMENT | PipingNetworkSegment18, PipingNetworkSegment3 |
| Shape10 | DIRECTION_OF_FLOW_SHAPE_FOR_SECONDARY_SEGMENT | PipingNetworkSegment19, PipingNetworkSegment20, PipingNetworkSegment21, PipingNetworkSegment22, PipingNetworkSegment23, PipingNetworkSegment8 |
| Shape16 | INSTRUMENTATION_BUBBLE_SHAPE_FIELD | ProcessInstrumentationFunction1 |
| Shape17 | INSTRUMENTATION_BUBBLE_SHAPE_CENTRAL | ProcessInstrumentationFunction2, ProcessInstrumentationFunction3, ProcessInstrumentationFunction4 |

# Shapes cheme-as-code adds

Those marked in `empty-sheet.xml` are in it (after the reference shapes); for any other, or a sheet made before one was added, `cheme fragment shape NAME --sheet pid/<sheet>.xml` prints the Shape to paste into its catalogue, or says it is there already. Most are ISO 10628-2 symbols with their registration number (`ISO10628:2012-<number>-A`); the few cheme-as-code draws itself carry their name instead (their ISO number is not checked), as the reference does for its shapes without a number. Never invent a number, nor borrow one from a symbol of another name. Ports are the symbol's connection points at scale 1 (sheet mm from its centre, Y down): place nozzles and pipe ends there, scaled and rotated with the symbol.

| id | name | ISO 10628 number | meaning | scale on A3 | default for | ports | in empty-sheet.xml |
|---|---|---|---|---|---|---|---|
| Shape_Pump | PUMP_SHAPE | ISO10628:2012-2301-A | pump, general | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpCentrifugal | PUMP_CENTRIFUGAL_SHAPE | ISO10628:2012-2322-A | pump, centrifugal | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpReciprocating | PUMP_RECIPROCATING_SHAPE | ISO10628:2012-X8094-A | pump, reciprocating (piston) | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpGear | PUMP_GEAR_SHAPE | ISO10628:2012-8091-A | pump, gear (rotary) | 1.0 (15 mm circle) | RotaryPump | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpScrew | PUMP_SCREW_SHAPE | ISO10628:2012-8092-A | pump, screw | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpProgressiveCavity | PUMP_PROGRESSIVE_CAVITY_SHAPE | ISO10628:2012-8093-A | pump, progressive cavity (eccentric screw) | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpDiaphragm | PUMP_DIAPHRAGM_SHAPE | ISO10628:2012-X8095-A | pump, diaphragm | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_PumpVacuum | PUMP_VACUUM_SHAPE | ISO10628:2012-2302-A | vacuum pump | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_Ejector | EJECTOR_SHAPE | ISO10628:2012-X8163-A | ejector or jet pump: motive inlet left, suction below, discharge right | 1.0 (20 x 8 mm) | EjectorPump, AirEjector | motive_in -10,0, suction -6,4, discharge 10,0 |  |
| Shape_Compressor | COMPRESSOR_SHAPE | ISO10628:2012-2302-A | compressor, general | 1.0 (15 mm circle); 1.5 for a main air compressor | Compressor | suction -7.5,0, discharge 7.5,0 |  |
| Shape_CompressorCentrifugal | COMPRESSOR_CENTRIFUGAL_SHAPE | ISO10628:2012-X8179-A | compressor, centrifugal | 1.0 (15 mm circle); 1.5 for a main air compressor | CentrifugalCompressor | suction -7.5,0, discharge 7.5,0 | yes |
| Shape_CompressorReciprocating | COMPRESSOR_RECIPROCATING_SHAPE | ISO10628:2012-X8097-A | compressor, reciprocating (piston) | 1.0 (15 mm circle) | ReciprocatingCompressor | suction -7.5,0, discharge 7.5,0 |  |
| Shape_CompressorRotary | COMPRESSOR_ROTARY_SHAPE | ISO10628:2012-X8105-A | compressor, rotary | 1.0 (15 mm circle) | RotaryCompressor | suction -7.5,0, discharge 7.5,0 |  |
| Shape_CompressorScrew | COMPRESSOR_SCREW_SHAPE | ISO10628:2012-X8161-A | compressor, screw | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_CompressorLiquidRing | COMPRESSOR_LIQUID_RING_SHAPE | ISO10628:2012-X8162-A | compressor or vacuum pump, liquid ring | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_CompressorTurbo | COMPRESSOR_TURBO_SHAPE | ISO10628:2012-X8102-A | compressor, turbo | 1.0 (15 mm circle) |  | suction -7.5,0, discharge 7.5,0 |  |
| Shape_Blower | BLOWER_SHAPE | ISO10628:2012-X8164-A | blower | 1.0 (15 mm circle) | Blower, CentrifugalBlower, AxialBlower | suction -7.5,0, discharge 7.5,0 | yes |
| Shape_Fan | FAN_SHAPE | ISO10628:2012-X8164-A | fan | 1.0 (15 x 3 mm) | Fan, RadialFan, AxialFan | suction -7.5,-1.42, discharge 7.5,-1.42 |  |
| Shape_Turbine | TURBINE_SHAPE | ISO10628:2012-2571-A | turbine or expander: narrow inlet left, wide outlet right | 1.0 (9 x 15 mm); mirror for flow right to left | Turbine, GasTurbine, SteamTurbine | inlet -4.5,0, outlet 4.5,0 | yes |
| Shape_Motor | MOTOR_SHAPE | ISO10628:2012-C0082-A | electric motor (drive) | 1.0 (10 mm circle) | Motor, AlternatingCurrentMotor |  |  |
| Shape_Vessel | VESSEL_SHAPE | ISO10628:2012-301-A | vessel, general | 1.0 (15 x 25 mm) |  | N1 0,-12.5, N2 0,12.5 |  |
| Shape_VesselDishedEnds | VESSEL_DISHED_ENDS_SHAPE | ISO10628:2012-2062-A | vessel with dished ends (drum, reactor, flash drum) | 1.0 (18 x 25 mm); stretch with ScaleY |  | N1 0,-12.5, N2 0,12.5 |  |
| Shape_VesselDishedEndsJacket | VESSEL_DISHED_ENDS_JACKET_SHAPE | ISO10628:2012-X2069-A | vessel with dished ends and heating/cooling jacket | 1.0 (18 x 25 mm) |  | N1 0,-12.5, N2 0,12.5, jacket_in -8.98,7.7, jacket_out 8.98,-7.7 |  |
| Shape_VesselTubeCoil | VESSEL_TUBE_COIL_SHAPE | ISO10628:2012-X8000-A | vessel with full-tube heating/cooling coil | 1.0 (25 mm) |  | N1 0,-12.5, N2 0,12.5, coil_in -12.5,7.5, coil_out 12.5,-7.5 |  |
| Shape_VesselConicalEnds | VESSEL_CONICAL_ENDS_SHAPE | ISO10628:2012-X8009-A | vessel with conical roof and bottom | 1.0 (18 x 25 mm) |  | N1 0,-12.5, N2 0,12.5 |  |
| Shape_VesselDishedBottomFlatRoof | VESSEL_DISHED_BOTTOM_FLAT_ROOF_SHAPE | ISO10628:2012-X8007-A | vessel with dished bottom and surface indication | 1.0 (20 x 25 mm) |  | N1 0,-12.5, N2 0,12.5 |  |
| Shape_TankOpen | TANK_OPEN_SHAPE | ISO10628:2012-2061-A | tank, open (basin) | 1.0 (30 x 21 mm) |  | N1 -15,-10.5, N2 0,10.5 |  |
| Shape_TankConeRoof | TANK_CONE_ROOF_SHAPE | ISO10628:2012-X2063-A | storage tank with flat bottom and cone roof | 1.0-2.0 (20 x 25 mm at 1.0) |  | N1 0,-12.5, N2 0,12.5 | yes |
| Shape_TankDishedRoof | TANK_DISHED_ROOF_SHAPE | ISO10628:2012-X8200-A | storage tank with flat bottom and dished roof | 1.0-2.0 (20 x 30 mm at 1.0) |  | N1 0,-15, N2 0,15 |  |
| Shape_TankConicalBottom | TANK_CONICAL_BOTTOM_SHAPE | ISO10628:2012-X2062-A | tank with conical bottom | 1.0 (18 x 30 mm) |  | N1 0,-15, N2 0,15 |  |
| Shape_Silo | SILO_SHAPE | ISO10628:2012-2064-A | bunker or silo with conical bottom (bulk solids) | 1.0 (18 x 30 mm) | Silo | N1 -9,-15, N2 0,15 |  |
| Shape_Column | COLUMN_SHAPE | ISO10628:2012-X8100-A | column, general (20 x 50 mm); stretch it with ScaleY | ScaleX 1.0, ScaleY 1.0-3.0 (50-150 mm high); draw beds/trays as markers on it |  | feed -10,0, overhead 0,-25, bottoms 0,25 | yes |
| Shape_ColumnTrays | COLUMN_TRAYS_SHAPE | ISO10628:2012-X8101-A | column with trays, general | ScaleX 1.0, ScaleY 1.0-3.0 | ProcessColumn | feed -10,0, overhead 0,-25, bottoms 0,25 |  |
| Shape_ColumnFixedBed | COLUMN_FIXED_BED_SHAPE | ISO10628:2012-X8015-A | column with fixed bed (packed column, absorber, adsorber) | ScaleX 1.0, ScaleY 1.0-3.0 |  | feed -15,0, overhead 0,-25, bottoms 0,25 |  |
| Shape_ColumnBubbleCapTrays | COLUMN_BUBBLE_CAP_TRAYS_SHAPE | ISO10628:2012-X8011-A | column with bubble-cap trays | ScaleX 1.0, ScaleY 1.0-3.0 |  | feed -12.55,0, overhead 0,-25, bottoms 0,25 |  |
| Shape_ColumnValveTrays | COLUMN_VALVE_TRAYS_SHAPE | ISO10628:2012-X8012-A | column with valve trays | ScaleX 1.0, ScaleY 1.0-3.0 |  | feed -15,0, overhead 0,-25, bottoms 0,25 |  |
| Shape_HeatExchanger | HEAT_EXCHANGER_SHAPE | ISO10628:2012-X8079-A | heat exchanger, cooler or heater, general | 1.0 (15 mm) | HeatExchanger, Heater | tube_in 7.5,-3.33, tube_out 7.5,3.33, shell_in -0.83,-6.67, shell_out -0.83,6.67 | yes |
| Shape_HeatExchangerFixedTubes | HEAT_EXCHANGER_FIXED_TUBES_SHAPE | ISO10628:2012-2511-A | shell-and-tube heat exchanger, fixed tube sheets | 1.0 (35 x 14 mm) |  | tube_in -17.5,0, tube_out 17.5,0, shell_in -7,-7, shell_out 7,7 | yes |
| Shape_HeatExchangerFloatingHead | HEAT_EXCHANGER_FLOATING_HEAD_SHAPE | ISO10628:2012-2512-A | shell-and-tube heat exchanger, floating head | 1.0 (35 x 14 mm) |  | tube_in -14,-6.81, tube_out -14,6.81, shell_in 3.5,6.81, shell_out 3.5,-6.81 |  |
| Shape_HeatExchangerUTube | HEAT_EXCHANGER_U_TUBE_SHAPE | ISO10628:2012-2513-A | shell-and-tube heat exchanger, U tubes | 1.0 (35 x 11 mm) |  | tube_in -13.12,-3.5, tube_out -13.12,3.5, shell_in 0,3.5, shell_out 0,-3.5 |  |
| Shape_HeatExchangerPlate | HEAT_EXCHANGER_PLATE_SHAPE | ISO10628:2012-2516-A | plate heat exchanger | 1.0 (20 x 8 mm) |  | hot_in -9,-4, hot_out 9,-4, cold_in 9,4, cold_out -9,4 |  |
| Shape_HeatExchangerSpiral | HEAT_EXCHANGER_SPIRAL_SHAPE | ISO10628:2012-X2517-A | spiral heat exchanger | 1.0 (15 mm circle) | SpiralHeatExchanger | hot_in -7.5,0, hot_out 0,7.5, cold_in 7.5,0, cold_out 0,-7.5 |  |
| Shape_HeatExchangerDoublePipe | HEAT_EXCHANGER_DOUBLE_PIPE_SHAPE | ISO10628:2012-X2515-A | double-pipe heat exchanger | 1.0 (25 x 12 mm) |  | tube_in -12.5,-3.57, tube_out -12.5,3.57, shell_in -1.78,5.95, shell_out -1.78,-5.95 |  |
| Shape_AirCooler | AIR_COOLER_SHAPE | ISO10628:2012-X2505-A | air cooler: finned tubes with fan | 1.0 (20 x 25 mm) | AirCoolingSystem | tube_in -7.5,8.75, tube_out 7.5,8.75 | yes |
| Shape_KettleReboiler | KETTLE_REBOILER_SHAPE | ISO10628:2012-X8131-A | kettle reboiler | 1.0 (35 x 23 mm) |  | tube_in -17.5,-3.63, tube_out -17.5,1.62, shell_in 2.62,4.25, vapour_out 6.12,-11.5, liquid_out 17.5,-1 |  |
| Shape_ElectricHeater | ELECTRIC_HEATER_SHAPE | ISO10628:2012-X8132-A | electric heater | 1.0 (20 x 16 mm) | ElectricHeater | inlet -10,0, outlet 10,0 | yes |
| Shape_Furnace | FURNACE_SHAPE | ISO10628:2012-2533-A | furnace, fired heater | 1.0 (20 x 25 mm) | Furnace | inlet -10,5, outlet 10,8.75 |  |
| Shape_Boiler | BOILER_SHAPE | ISO10628:2012-2532-A | boiler, steam generator | 1.0 (20 mm) | Boiler, SteamGenerator | feedwater_in -10,4, outlet 0,-10 |  |
| Shape_ThinFilmEvaporator | THIN_FILM_EVAPORATOR_SHAPE | ISO10628:2012-X8133-A | thin-film evaporator | 1.0 (20 x 25 mm) | ThinFilmEvaporator | feed -10,-10, vapour_out 10,-10, bottoms 0,12.5 |  |
| Shape_CoolingTower | COOLING_TOWER_SHAPE | ISO10628:2012-2521-A | cooling tower, general | 1.0 (25 mm) | CoolingTower, DryCoolingTower | inlet -12.5,10, outlet 12.5,10 |  |
| Shape_CoolingTowerWet | COOLING_TOWER_WET_SHAPE | ISO10628:2012-8114-A | wet cooling tower, induced draught | 1.0 (15 x 25 mm) | WetCoolingTower | water_in -7.5,-3.75, water_out 0,12.5 |  |
| Shape_Separator | SEPARATOR_SHAPE | ISO10628:2012-X8081-A | separator, general | 1.0 (15 x 25 mm) | Separator, MechanicalSeparator | inlet -7.5,-10, light_out 7.5,-10, heavy_out 0,12.5 |  |
| Shape_SeparatorGravity | SEPARATOR_GRAVITY_SHAPE | ISO10628:2012-X8031-A | gravity separator, settler | 1.0 (15 x 25 mm) | GravitationalSeparator | inlet 0,-12.5, overflow_out 7.5,-3.75, underflow_out 0,12.5 |  |
| Shape_Cyclone | CYCLONE_SHAPE | ISO10628:2012-X2618-A | cyclone | 1.0 (15 x 25 mm) |  | inlet -7.5,-3.75, gas_out 0,-12.5, solids_out 0,12.5 |  |
| Shape_Scrubber | SCRUBBER_SHAPE | ISO10628:2012-X8124-A | wet scrubber | 1.0 (15 x 25 mm) | ScrubbingSeparator | gas_in 0,-12.5, gas_out 7.5,-3.75, liquid_out 0,12.5 |  |
| Shape_LiquidFilter | LIQUID_FILTER_SHAPE | ISO10628:2012-X8116-A | filter, liquid (also a general filter) | 1.0 (15 x 25 mm) | Filter, LiquidFilter | inlet 0,-12.5, outlet 0,12.5 |  |
| Shape_GasFilter | GAS_FILTER_SHAPE | ISO10628:2012-X8122-A | filter, gas | 1.0 (15 x 25 mm) | GasFilter | inlet 0,-12.5, outlet 0,12.5 | yes |
| Shape_Dryer | DRYER_SHAPE | ISO10628:2012-C0046-A | dryer, general | 1.0 (20 x 25 mm) | Dryer | inlet 0,-12.5, outlet 0,12.5 |  |
| Shape_StaticMixer | STATIC_MIXER_SHAPE | ISO10628:2012-X2673-A | static mixer | 1.0 (15 mm) | StaticMixer | inlet -7.5,0, outlet 7.5,0 |  |
| Shape_Mixer | MIXER_SHAPE | ISO10628:2012-X2672-A | mixer, rotary | 1.0 (20 x 12 mm) | Mixer, RotaryMixer | inlet -10,0, outlet 10,0 |  |
| Shape_Agitator | AGITATOR_SHAPE | ISO10628:2012-2672-A | agitator, general: draw it inside its vessel | 1.0 (7 x 10 mm) | Agitator |  |  |
| Shape_AgitatorImpeller | AGITATOR_IMPELLER_SHAPE | ISO10628:2012-C2024-A | agitator, impeller | 1.0 (9 x 10 mm) |  |  |  |
| Shape_AgitatorTurbine | AGITATOR_TURBINE_SHAPE | ISO10628:2012-C2027-A | agitator, turbine (disc) | 1.0 (6 x 10 mm) |  |  |  |
| Shape_AgitatorAnchor | AGITATOR_ANCHOR_SHAPE | ISO10628:2012-C2022-A | agitator, anchor | 1.0 (10 mm) |  |  |  |
| Shape_Valve | VALVE_SHAPE | ISO10628:2012-2101-A | valve, general (two-way) | 0.4 inline (ends 2 mm from the centre) |  | inlet -5,0, outlet 5,0 |  |
| Shape_GateValve | GATE_VALVE_SHAPE | ISO10628:2012-X8074-A | gate valve | 0.4 inline (ends 2 mm from the centre) | GateValve | inlet -5,0, outlet 5,0 | yes |
| Shape_GlobeValveIso | GLOBE_VALVE_ISO_SHAPE | ISO10628:2012-X8068-A | globe valve | 0.4 inline (ends 2 mm from the centre) |  | inlet -5,0, outlet 5,0 |  |
| Shape_BallValveIso | BALL_VALVE_ISO_SHAPE | ISO10628:2012-X8071-A | ball valve | 0.4 inline (ends 2 mm from the centre) |  | inlet -5,0, outlet 5,0 |  |
| Shape_ButterflyValveIso | BUTTERFLY_VALVE_ISO_SHAPE | ISO10628:2012-X8075-A | butterfly valve | 0.4 inline (ends 2 mm from the centre) |  | inlet -5,0, outlet 5,0 |  |
| Shape_CheckValve | CHECK_VALVE_SHAPE | ISO10628:2012-X8077-A | check (non-return) valve, general: flow left to right | 0.4 inline (ends 2 mm from the centre) | CheckValve | inlet -5,0, outlet 5,0 |  |
| Shape_SwingCheckValveIso | SWING_CHECK_VALVE_ISO_SHAPE | ISO10628:2012-X8165-A | swing check valve | 0.4 inline |  | inlet -4.14,0.42, outlet 5,0.42 |  |
| Shape_NeedleValve | NEEDLE_VALVE_SHAPE | ISO10628:2012-X8076-A | needle valve | 0.4 inline (ends 2 mm from the centre) | NeedleValve | inlet -5,0.56, outlet 5,0.56 |  |
| Shape_AngleValve | ANGLE_VALVE_SHAPE | ISO10628:2012-2102-A | angle valve: inlet below, outlet right | 0.4 | AngleValve | inlet -1.67,5, outlet 5,-1.67 |  |
| Shape_ThreeWayValve | THREE_WAY_VALVE_SHAPE | ISO10628:2012-2103-A | three-way valve | 0.4 |  | inlet -5,-1.25, outlet 5,-1.25 |  |
| Shape_ControlValve | CONTROL_VALVE_SHAPE | ISO10628:2012-X8087-A | control valve (continuously operated) | 0.4 inline |  | inlet -4,0.1, outlet 4,0.1 |  |
| Shape_SafetyValveSpringLoaded | SAFETY_VALVE_SPRING_LOADED_SHAPE | ISO10628:2012-X2124-A | safety valve, spring loaded | 0.4-0.6 |  | inlet -4.44,2.78, outlet 4.44,2.78 |  |
| Shape_AngleSafetyValveIso | ANGLE_SAFETY_VALVE_ISO_SHAPE | ISO10628:2012-X2125-A | angle safety valve, spring loaded: inlet below, outlet right | 0.4-0.6 |  | inlet -1,5, outlet 3,1 |  |
| Shape_RuptureDisc | RUPTURE_DISC_SHAPE | ISO10628:2012-X8080-A | rupture (bursting) disc | 0.4-0.6 | RuptureDisc | inlet -2.5,0, outlet 2.5,0 |  |
| Shape_SteamTrap | STEAM_TRAP_SHAPE | ISO10628:2012-2181-A | steam trap | 0.4-0.6 | SteamTrap | inlet -4.99,0, outlet 4.99,0 |  |
| Shape_FlameArrestor | FLAME_ARRESTOR_SHAPE | ISO10628:2012-2036-A | flame arrestor | 0.4-0.6 | FlameArrestor | inlet -2,0, outlet 2,0 |  |
| Shape_ReducerIso | REDUCER_ISO_SHAPE | ISO10628:2012-516-A | reducer | 0.4 |  | inlet -5,0, outlet 5,0 |  |
| Shape_Strainer | STRAINER_SHAPE | ISO10628:2012-X8150-A | strainer (conical) | 0.4-0.6 | Strainer, ConicalStrainer | inlet -5,0, outlet 5,0 |  |
| Shape_SightGlassIlluminated | SIGHT_GLASS_ILLUMINATED_SHAPE | ISO10628:2012-X8089-A | sight glass with lighting (illuminated) | 0.4-0.6 | IlluminatedSightGlass | inlet -5,-1.87, outlet 5,-1.87 |  |
| Shape_Flare | FLARE_SHAPE | ISO10628:2012-2591-A | flare stack | 1.0 (25 mm) | Flare | inlet 0,12.38 |  |
| Shape_Chimney | CHIMNEY_SHAPE | ISO10628:2012-2041-A | chimney, stack | 1.0 (25 mm) | Chimney | inlet 0,12.5 |  |
| Shape_AxialCompressor | AXIAL_COMPRESSOR_SHAPE | name (drawn here, ISO number not checked) | compressor, axial: wide inlet left, narrow outlet right | 1.0 (20 x 15 mm) | AxialCompressor |  | yes |
| Shape_ColumnPackedBed | COLUMN_PACKED_BED_SHAPE | name (drawn here, ISO number not checked) | packed bed (or adsorbent bed) marker inside a column or vessel: crossed box 20 x 20 mm | ScaleX = column ScaleX, ScaleY = bed height / 20 |  |  | yes |
| Shape_ColumnTray | COLUMN_TRAY_SHAPE | name (drawn here, ISO number not checked) | one tray inside a column (downcomer on the right); draw one per tray shown | ScaleX = column ScaleX, ScaleY 1.0; IsMirrored for the downcomer on the left |  |  | yes |
| Shape_Silencer | SILENCER_SHAPE | name (drawn here, ISO number not checked) | silencer (Plant/Piping.Silencer, an inline fitting): ends at x = -6 and 6 | 0.5 inline (ends 3 mm from the centre: fragment valve --class Silencer) |  |  | yes |
| Shape_AmbientVaporizer | AMBIENT_VAPORIZER_SHAPE | name (drawn here, ISO number not checked) | ambient-air vaporizer (finned tubes), class HeatExchanger or AirCoolingSystem | 1.0 (16 x 25 mm) |  |  | yes |
| Shape_PlateFinHeatExchanger | PLATE_FIN_HEAT_EXCHANGER_SHAPE | name (drawn here, ISO number not checked) | plate-fin (brazed aluminium) heat exchanger, class PlateHeatExchanger | 1.0-3.0 (16 x 30 mm at 1.0) |  |  | yes |
