/**
 * The realistic look of the layout view: physically based surfaces by material hint, an
 * environment map (three's `RoomEnvironment`), a soft shadow map from the sun and screen-space
 * ambient occlusion (a GTAO pass) behind an effect composer with multisampling.
 *
 * Engineering detail with nicer light, not photorealism: no image textures except the grating's
 * generated alpha pattern.
 */
import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { GTAOPass } from "three/examples/jsm/postprocessing/GTAOPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/**
 * Surfaces of the realistic look by material hint: colour (when the material, not the item,
 * decides it), roughness, metalness and whether a translucent layer turns solid.
 */
export const REAL_SURFACE: Record<string, { color?: string; roughness: number; metalness: number; solid?: boolean }> = {
  shell: { roughness: 0.42, metalness: 0.15 },
  painted: { roughness: 0.42, metalness: 0.15 },
  steel: { color: "#59626d", roughness: 0.5, metalness: 0.4 },
  casing: { roughness: 0.4, metalness: 0.45 },
  motor: { roughness: 0.45, metalness: 0.25 },
  plates: { roughness: 0.45, metalness: 0.35 },
  fan: { roughness: 0.35, metalness: 0.6 },
  pipe: { roughness: 0.35, metalness: 0.4 },
  nozzle: { color: "#9aa1a9", roughness: 0.35, metalness: 0.65 },
  inline: { roughness: 0.4, metalness: 0.35 },
  // Insulated lines wear aluminium jacketing.
  insulation: { color: "#c9cfd6", roughness: 0.38, metalness: 0.7, solid: true },
  insulation_jacket: { color: "#c9cfd6", roughness: 0.38, metalness: 0.7, solid: true },
  insulation_personnel: { color: "#9aa1a8", roughness: 0.55, metalness: 0.5, solid: true },
  valve: { roughness: 0.4, metalness: 0.35 },
  handwheel: { roughness: 0.4, metalness: 0.3 },
  actuator: { roughness: 0.35, metalness: 0.3 },
  instrument: { roughness: 0.35, metalness: 0.3 },
  grating: { color: "#a9b0b6", roughness: 0.6, metalness: 0.35, solid: true },
  galvanised: { color: "#a2aab2", roughness: 0.5, metalness: 0.65 },
  stainless: { color: "#c6ccd2", roughness: 0.22, metalness: 0.9 },
  concrete: { color: "#b3afa5", roughness: 0.95, metalness: 0 },
  handrail: { roughness: 0.45, metalness: 0.2 },
  guard: { roughness: 0.45, metalness: 0.2 },
  flange: { color: "#8f979f", roughness: 0.35, metalness: 0.7 },
  cage: { roughness: 0.45, metalness: 0.2 },
  stair: { roughness: 0.55, metalness: 0.4 },
  wall: { roughness: 0.85, metalness: 0.05 },
  cladding: { roughness: 0.6, metalness: 0.35 },
  building: { roughness: 0.75, metalness: 0.1 },
  roof: { roughness: 0.6, metalness: 0.35 },
  door: { roughness: 0.5, metalness: 0.3 },
  glass: { roughness: 0.05, metalness: 0.1 },
  louvre: { roughness: 0.5, metalness: 0.4 },
  crane: { roughness: 0.45, metalness: 0.25 },
  fire_wall: { color: "#b5ada0", roughness: 0.95, metalness: 0 },
  road: { color: "#5d6166", roughness: 0.95, metalness: 0 },
  area: { roughness: 1, metalness: 0 },
  sleeve: { roughness: 0.5, metalness: 0.2 },
  // Trays and ducts keep their system's colour (power or instrument, supply or extract air) on a sheet-metal surface.
  tray_power: { roughness: 0.5, metalness: 0.55 },
  tray_instrument: { roughness: 0.5, metalness: 0.55 },
  junction_box: { roughness: 0.4, metalness: 0.3 },
  ahu: { roughness: 0.45, metalness: 0.4 },
  duct_supply: { roughness: 0.45, metalness: 0.55 },
  duct_extract: { roughness: 0.45, metalness: 0.55 },
  duct_outdoor: { roughness: 0.45, metalness: 0.55 },
  duct_exhaust: { roughness: 0.45, metalness: 0.55 },
  grille_supply: { roughness: 0.5, metalness: 0.4 },
  grille_extract: { roughness: 0.5, metalness: 0.4 },
};

/** Metres of the site one repeat of the grating texture covers. */
export const GRATING_PITCH = 0.1;

/**
 * The alpha pattern of a pressed grating (bearing bars every third of the repeat, a cross bar per
 * repeat), with its own mipmaps: the bars widen with distance and the far levels close up, so a
 * floor seen from afar reads as a floor rather than fading out under the alpha test.
 */
export function gratingTexture(size = 64): THREE.Texture {
  const levels: (HTMLCanvasElement | { data: Uint8Array; width: number; height: number })[] = [];
  for (let s = size, level = 0; s >= 1; s = Math.floor(s / 2), level++) levels.push(gratingLevel(s, level));
  const texture = new THREE.Texture(levels[0] as unknown as HTMLImageElement);
  texture.mipmaps = levels as unknown as THREE.Texture["mipmaps"];
  texture.generateMipmaps = false;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.minFilter = THREE.LinearMipmapLinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  return texture;
}

function gratingLevel(s: number, level: number): HTMLCanvasElement | { data: Uint8Array; width: number; height: number } {
  // Grey levels: 255 is steel, 0 is open.
  const data = new Uint8Array(s * s * 4);
  const solid = level >= 3;
  const bar = Math.max(1, Math.round((s / 64) * 6 * (1 + level * 0.35)));
  for (let y = 0; y < s; y++)
    for (let x = 0; x < s; x++) {
      const bearing = x % Math.max(1, Math.round(s / 3)) < bar;
      const cross = y < Math.max(1, Math.round(bar * 0.7));
      const v = solid ? 235 : bearing || cross ? 255 : 0;
      const i = (y * s + x) * 4;
      data[i] = data[i + 1] = data[i + 2] = v;
      data[i + 3] = 255;
    }
  if (typeof document === "undefined") return { data, width: s, height: s };
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = s;
  const ctx = canvas.getContext("2d");
  if (!ctx) return { data, width: s, height: s };
  const image = ctx.createImageData(s, s);
  image.data.set(data);
  ctx.putImageData(image, 0, 0);
  return canvas;
}

export interface Realism {
  /** Render one frame through the composer. */
  render(camera: THREE.Camera): void;
  setSize(width: number, height: number): void;
  /** The environment map (set on the scene while realistic). */
  environment: THREE.Texture;
  dispose(): void;
}

/** The composer, ambient occlusion and environment of the realistic look (made on first use). */
export function createRealism(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera, width: number, height: number): Realism {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const room = new RoomEnvironment();
  const environment = pmrem.fromScene(room, 0.04).texture;
  room.dispose();
  pmrem.dispose();

  const ratio = renderer.getPixelRatio();
  const target = new THREE.WebGLRenderTarget(width * ratio, height * ratio, { type: THREE.HalfFloatType, samples: 4 });
  const composer = new EffectComposer(renderer, target);
  const renderPass = new RenderPass(scene, camera);
  composer.addPass(renderPass);
  const ao = new GTAOPass(scene, camera, width, height);
  // Metres: the AO reaches about a pipe's or a beam's size.
  ao.updateGtaoMaterial({ radius: 1.2, distanceExponent: 1.5, thickness: 2, scale: 1.8, samples: 16, screenSpaceRadius: false });
  ao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 10, rings: 3, samples: 16 });
  ao.blendIntensity = 1;
  composer.addPass(ao);
  composer.addPass(new OutputPass());
  composer.setSize(width, height);
  let perspective: boolean | null = null;

  return {
    environment,
    render(cam) {
      renderPass.camera = cam;
      ao.camera = cam;
      const isPerspective = "isPerspectiveCamera" in cam && cam.isPerspectiveCamera === true;
      if (perspective !== isPerspective) {
        perspective = isPerspective;
        ao.gtaoMaterial.defines.PERSPECTIVE_CAMERA = isPerspective ? 1 : 0;
        ao.gtaoMaterial.needsUpdate = true;
        ao.depthRenderMaterial.defines.PERSPECTIVE_CAMERA = isPerspective ? 1 : 0;
        ao.depthRenderMaterial.needsUpdate = true;
      }
      composer.render();
    },
    setSize(w, h) {
      composer.setPixelRatio(renderer.getPixelRatio());
      composer.setSize(w, h);
    },
    dispose() {
      ao.dispose();
      composer.dispose();
      target.dispose();
      environment.dispose();
    },
  };
}
