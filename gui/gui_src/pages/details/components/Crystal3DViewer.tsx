import { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';

interface Crystal3DViewerProps {
  pmc_id?: string;
  isOpen: boolean;
  onClose: () => void;
  cifContent?: string;
  pdbContent?: string;
}

// ---------------------------------------------------------------------------
// Atom data — radius values are covalent radii in Angstrom
// ---------------------------------------------------------------------------
const ATOM_DATA: Record<string, { color: number; radius: number; name: string }> = {
  H:  { color: 0xffffff, radius: 0.31, name: 'Hydrogen' },
  C:  { color: 0x404040, radius: 0.77, name: 'Carbon' },
  N:  { color: 0x3050f8, radius: 0.75, name: 'Nitrogen' },
  O:  { color: 0xff2200, radius: 0.73, name: 'Oxygen' },
  S:  { color: 0xffcc00, radius: 1.02, name: 'Sulfur' },
  P:  { color: 0xff8000, radius: 1.06, name: 'Phosphorus' },
  F:  { color: 0x90e050, radius: 0.71, name: 'Fluorine' },
  Cl: { color: 0x1ff01f, radius: 0.99, name: 'Chlorine' },
  Br: { color: 0xa62929, radius: 1.14, name: 'Bromine' },
  I:  { color: 0x940094, radius: 1.33, name: 'Iodine' },
  Na: { color: 0xab5cf2, radius: 1.54, name: 'Sodium' },
  K:  { color: 0x8f40d4, radius: 1.96, name: 'Potassium' },
  Ca: { color: 0x3dff00, radius: 1.74, name: 'Calcium' },
  Fe: { color: 0xe06633, radius: 1.25, name: 'Iron' },
  Mg: { color: 0x8aff00, radius: 1.45, name: 'Magnesium' },
  Zn: { color: 0x7d80b0, radius: 1.22, name: 'Zinc' },
};
const DEFAULT_ATOM = { color: 0xcccccc, radius: 0.8, name: 'Unknown' };
function getAtomData(el: string) { return ATOM_DATA[el] || DEFAULT_ATOM; }

// Elements that act as hydrogen-bond donors / acceptors
const HBOND_ELEMENTS = new Set(['N', 'O', 'F']);

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Atom {
  element: string;
  x: number; y: number; z: number;         // cartesian
  fx?: number; fy?: number; fz?: number;   // fractional (crystals only)
}
interface CellVecs {
  a: [number, number, number];
  b: [number, number, number];
  c: [number, number, number];
  m: number[][];  // 3x3, cart = m . frac
  params: { a: number; b: number; c: number; alpha: number; beta: number; gamma: number };
}
interface StructureData {
  atoms: Atom[];
  cell: CellVecs | null;
  symOps: string[];
}

type Packing = 'asym' | 'cell' | 'super';
type DisplayStyle = 'ball-stick' | 'spacefill' | 'wireframe' | 'stick';

// ---------------------------------------------------------------------------
// Symmetry
// ---------------------------------------------------------------------------

// Parse one component of a symmetry operator: "-y", "x-y", "z+1/3", "1/2-x"
// Returns [cx, cy, cz, constant].
function parseSymComponent(src: string): [number, number, number, number] {
  let cx = 0, cy = 0, cz = 0, k = 0;
  const s = src.replace(/\s+/g, '').toLowerCase();
  const re = /([+-]?)([0-9]*\.?[0-9]*(?:\/[0-9]*\.?[0-9]+)?)\*?([xyz])?/g;
  let m: RegExpExecArray | null;
  let guard = 0;
  while ((m = re.exec(s)) !== null) {
    if (guard++ > 64) break;
    if (m[0] === '') {
      re.lastIndex++;
      if (re.lastIndex > s.length) break;
      continue;
    }
    const sign = m[1] === '-' ? -1 : 1;
    const numStr = m[2];
    let val: number;
    if (!numStr) val = 1;
    else if (numStr.includes('/')) {
      const [n, d] = numStr.split('/');
      val = parseFloat(n || '1') / parseFloat(d);
    } else val = parseFloat(numStr);
    if (isNaN(val)) val = 1;
    const v = m[3];
    if (v === 'x') cx += sign * val;
    else if (v === 'y') cy += sign * val;
    else if (v === 'z') cz += sign * val;
    else k += sign * val;
  }
  return [cx, cy, cz, k];
}

function compileSymOp(op: string) {
  const parts = op.split(',');
  if (parts.length !== 3) return null;
  const rows = parts.map(parseSymComponent);
  return (fx: number, fy: number, fz: number): [number, number, number] => [
    rows[0][0] * fx + rows[0][1] * fy + rows[0][2] * fz + rows[0][3],
    rows[1][0] * fx + rows[1][1] * fy + rows[1][2] * fz + rows[1][3],
    rows[2][0] * fx + rows[2][1] * fy + rows[2][2] * fz + rows[2][3],
  ];
}

const wrap01 = (v: number) => { const w = v % 1; return w < 0 ? w + 1 : w; };

// Expand the asymmetric unit into the full unit cell contents.
function expandSymmetry(atoms: Atom[], symOps: string[]) {
  const ops = symOps
    .map(compileSymOp)
    .filter(Boolean) as ((fx: number, fy: number, fz: number) => [number, number, number])[];
  if (!ops.length) ops.push((fx, fy, fz) => [fx, fy, fz]);

  const out: { fx: number; fy: number; fz: number; element: string }[] = [];
  const seen = new Set<string>();

  for (const at of atoms) {
    if (at.fx === undefined || at.fy === undefined || at.fz === undefined) continue;
    for (const op of ops) {
      const [px, py, pz] = op(at.fx, at.fy, at.fz);
      const fx = wrap01(px), fy = wrap01(py), fz = wrap01(pz);
      const key = `${at.element}|${fx.toFixed(3)}|${fy.toFixed(3)}|${fz.toFixed(3)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ fx, fy, fz, element: at.element });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Parsers
// ---------------------------------------------------------------------------
function parseCIF(text: string): StructureData {
  const lines = text.split('\n');
  let a = 1, b = 1, c = 1, alpha = 90, beta = 90, gamma = 90;
  const atomList: { element: string; fx: number; fy: number; fz: number }[] = [];
  const symOps: string[] = [];

  let headers: string[] = [], inAtomSite = false, inSymLoop = false;
  const colMap: Record<string, number> = {};

  // CIF numbers may carry an esd in parentheses: 5.1054(4)
  const stripNum = (s: string) => parseFloat(String(s).replace(/\(.*?\)/g, ''));

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('#')) continue;

    const aM  = line.match(/_cell_length_a\s+([\d.()]+)/);
    const bM  = line.match(/_cell_length_b\s+([\d.()]+)/);
    const cM  = line.match(/_cell_length_c\s+([\d.()]+)/);
    const alM = line.match(/_cell_angle_alpha\s+([\d.()]+)/);
    const beM = line.match(/_cell_angle_beta\s+([\d.()]+)/);
    const gaM = line.match(/_cell_angle_gamma\s+([\d.()]+)/);
    if (aM)  a = stripNum(aM[1]);
    if (bM)  b = stripNum(bM[1]);
    if (cM)  c = stripNum(cM[1]);
    if (alM) alpha = stripNum(alM[1]);
    if (beM) beta = stripNum(beM[1]);
    if (gaM) gamma = stripNum(gaM[1]);

    if (line === 'loop_') {
      headers = []; inAtomSite = false; inSymLoop = false;
      Object.keys(colMap).forEach(k => delete colMap[k]);
      continue;
    }

    // symmetry operator loop header
    if (/^_(symmetry_equiv_pos_as_xyz|space_group_symop_operation_xyz)/.test(line)) {
      inSymLoop = true; inAtomSite = false;
      continue;
    }

    if (line.startsWith('_atom_site_')) {
      inAtomSite = true; inSymLoop = false;
      colMap[line.split(/\s+/)[0]] = headers.length;
      headers.push(line);
      continue;
    }

    if (inSymLoop) {
      if (line.startsWith('_') || line.startsWith('loop_')) {
        inSymLoop = false;
      } else {
        // may be quoted and/or prefixed by an index:  1 'x, y, z'
        const q = line.match(/['"]([^'"]+)['"]/);
        let op = q ? q[1] : line.replace(/^\d+\s+/, '');
        op = op.trim();
        if (/^[-+0-9xyz/., ]+$/i.test(op) && op.split(',').length === 3) symOps.push(op);
        continue;
      }
    }

    if (inAtomSite && !line.startsWith('_') && line.length > 0) {
      const parts = line.split(/\s+/);
      const xKey = Object.keys(colMap).find(k => k.includes('fract_x'));
      const yKey = Object.keys(colMap).find(k => k.includes('fract_y'));
      const zKey = Object.keys(colMap).find(k => k.includes('fract_z'));
      const typeKey =
        Object.keys(colMap).find(k => k.includes('type_symbol')) ||
        Object.keys(colMap).find(k => k.includes('label'));
      if (xKey && yKey && zKey && typeKey) {
        const fx = stripNum(parts[colMap[xKey]]);
        const fy = stripNum(parts[colMap[yKey]]);
        const fz = stripNum(parts[colMap[zKey]]);
        let el = (parts[colMap[typeKey]] || '').replace(/[0-9_+\-]/g, '');
        el = el.charAt(0).toUpperCase() + (el.charAt(1) || '').toLowerCase();
        if (!isNaN(fx) && !isNaN(fy) && !isNaN(fz) && el) {
          atomList.push({ element: el, fx, fy, fz });
        }
      }
    }
    if (inAtomSite && line.startsWith('_') && !line.startsWith('_atom_site_')) inAtomSite = false;
  }

  const toRad = (deg: number) => deg * Math.PI / 180;
  const cosA = Math.cos(toRad(alpha)), cosB = Math.cos(toRad(beta)), cosG = Math.cos(toRad(gamma));
  const sinG = Math.sin(toRad(gamma));
  const vol = a * b * c * Math.sqrt(1 - cosA*cosA - cosB*cosB - cosG*cosG + 2*cosA*cosB*cosG);
  const m = [
    [a, b * cosG, c * cosB],
    [0, b * sinG, c * (cosA - cosB * cosG) / sinG],
    [0, 0, vol / (a * b * sinG)],
  ];

  const atoms: Atom[] = atomList.map(at => ({
    element: at.element,
    fx: at.fx, fy: at.fy, fz: at.fz,
    x: m[0][0]*at.fx + m[0][1]*at.fy + m[0][2]*at.fz,
    y: m[1][1]*at.fy + m[1][2]*at.fz,
    z: m[2][2]*at.fz,
  }));

  const cell: CellVecs = {
    a: [m[0][0], m[1][0], m[2][0]],
    b: [m[0][1], m[1][1], m[2][1]],
    c: [m[0][2], m[1][2], m[2][2]],
    m,
    params: { a, b, c, alpha, beta, gamma },
  };

  return { atoms, cell, symOps };
}

function parsePDB(text: string): StructureData {
  const atoms: Atom[] = [];
  for (const line of text.split('\n')) {
    if (!line.startsWith('ATOM') && !line.startsWith('HETATM')) continue;
    const x = parseFloat(line.substring(30, 38));
    const y = parseFloat(line.substring(38, 46));
    const z = parseFloat(line.substring(46, 54));
    let el = line.substring(76, 78).trim();
    if (!el) el = line.substring(12, 16).trim().replace(/[0-9]/g, '').charAt(0);
    el = el.charAt(0).toUpperCase() + (el.charAt(1) || '').toLowerCase();
    if (!isNaN(x)) atoms.push({ element: el, x, y, z });
  }
  return { atoms, cell: null, symOps: [] };
}

function parseXYZ(text: string): StructureData {
  const lines = text.split('\n').filter(l => l.trim());
  const n = parseInt(lines[0]);
  const atoms: Atom[] = [];
  for (let i = 2; i < 2 + n && i < lines.length; i++) {
    const parts = lines[i].trim().split(/\s+/);
    if (parts.length >= 4) {
      let el = parts[0];
      el = el.charAt(0).toUpperCase() + (el.charAt(1) || '').toLowerCase();
      atoms.push({ element: el, x: parseFloat(parts[1]), y: parseFloat(parts[2]), z: parseFloat(parts[3]) });
    }
  }
  return { atoms, cell: null, symOps: [] };
}

// ---------------------------------------------------------------------------
// Build the displayed structure from the raw parse result
// ---------------------------------------------------------------------------
function deriveStructure(
  raw: StructureData,
  packing: Packing,
  nx: number, ny: number, nz: number,
  showH: boolean,
): StructureData {
  let atoms: Atom[];

  if (!raw.cell || packing === 'asym') {
    atoms = raw.atoms;
  } else {
    const m = raw.cell.m;
    const cellAtoms = expandSymmetry(raw.atoms, raw.symOps);
    const rx = packing === 'super' ? nx : 1;
    const ry = packing === 'super' ? ny : 1;
    const rz = packing === 'super' ? nz : 1;

    atoms = [];
    for (let i = 0; i < rx; i++)
      for (let j = 0; j < ry; j++)
        for (let k = 0; k < rz; k++)
          for (const at of cellAtoms) {
            const fx = at.fx + i, fy = at.fy + j, fz = at.fz + k;
            atoms.push({
              element: at.element,
              fx, fy, fz,
              x: m[0][0]*fx + m[0][1]*fy + m[0][2]*fz,
              y: m[1][1]*fy + m[1][2]*fz,
              z: m[2][2]*fz,
            });
          }
  }

  if (!showH) atoms = atoms.filter(a => a.element !== 'H');
  return { atoms, cell: raw.cell, symOps: raw.symOps };
}

// ---------------------------------------------------------------------------
// Text sprite for axis labels
// ---------------------------------------------------------------------------
function makeLabel(text: string, color: string): THREE.Sprite {
  const canvas = document.createElement('canvas');
  canvas.width = 64; canvas.height = 64;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = color;
  ctx.font = 'bold 44px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 32, 32);
  const tex = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false }));
  sprite.scale.set(1.2, 1.2, 1.2);
  return sprite;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function Crystal3DViewer({ pmc_id, isOpen, onClose, cifContent, pdbContent }: Crystal3DViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const groupRef = useRef<THREE.Group | null>(null);
  const animFrameRef = useRef<number>(0);
  const atomMeshesRef = useRef<THREE.Mesh[]>([]);
  const rawDataRef = useRef<StructureData | null>(null);
  const displayDataRef = useRef<StructureData | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [atomCount, setAtomCount] = useState(0);
  const [hoverLabel, setHoverLabel] = useState('');
  const [spinning, setSpinning] = useState(false);
  const [displayStyle, setDisplayStyle] = useState<DisplayStyle>('ball-stick');
  const [showCell, setShowCell] = useState(true);
  const [showAxes, setShowAxes] = useState(true);
  const [showBonds, setShowBonds] = useState(true);
  const [showHBonds, setShowHBonds] = useState(true);
  const [showH, setShowH] = useState(true);
  const [atomRadius, setAtomRadius] = useState(0.35);
  const [bondTol, setBondTol] = useState(0.4);
  const [packing, setPacking] = useState<Packing>('cell');
  const [nx, setNx] = useState(2);
  const [ny, setNy] = useState(2);
  const [nz, setNz] = useState(2);
  const [cellParams, setCellParams] = useState<CellVecs['params'] | null>(null);
  const [symOpCount, setSymOpCount] = useState(0);
  const [hasCell, setHasCell] = useState(false);
  const [hbondCount, setHbondCount] = useState(0);
  const [elements, setElements] = useState<{ el: string; color: string; count: number }[]>([]);

  const stateRef = useRef({
    rotX: 0, rotY: 0, panX: 0, panY: 0, zoomDist: 20,
    isDragging: false, isRightDrag: false,
    prevMouse: { x: 0, y: 0 },
    spinning: false,
  });

  // -------------------------------------------------------------------------
  // Scene construction
  // -------------------------------------------------------------------------
  const buildScene = useCallback((
    data: StructureData,
    style: DisplayStyle,
    radius: number,
    tol: number,
    cellOn: boolean,
    bondsOn: boolean,
    hbondsOn: boolean,
    axesOn: boolean,
    hydrogensOn: boolean,
    pack: Packing,
    rx: number, ry: number, rz: number,
  ) => {
    const group = groupRef.current;
    const scene = sceneRef.current;
    if (!group || !scene) return;

    while (group.children.length) group.remove(group.children[0]);
    atomMeshesRef.current = [];

    // ---- centering -------------------------------------------------------
    let cx = 0, cy = 0, cz = 0;
    const rep = pack === 'super' ? [rx, ry, rz] : [1, 1, 1];
    if (data.cell && pack !== 'asym') {
      const m = data.cell.m;
      const fx = rep[0] / 2, fy = rep[1] / 2, fz = rep[2] / 2;
      cx = m[0][0]*fx + m[0][1]*fy + m[0][2]*fz;
      cy = m[1][1]*fy + m[1][2]*fz;
      cz = m[2][2]*fz;
    } else if (data.atoms.length) {
      cx = data.atoms.reduce((s, a) => s + a.x, 0) / data.atoms.length;
      cy = data.atoms.reduce((s, a) => s + a.y, 0) / data.atoms.length;
      cz = data.atoms.reduce((s, a) => s + a.z, 0) / data.atoms.length;
    }
    const atoms = data.atoms.map(a => ({ ...a, x: a.x - cx, y: a.y - cy, z: a.z - cz }));
    displayDataRef.current = { ...data, atoms };

    // ---- camera framing --------------------------------------------------
    let maxDist = 0;
    atoms.forEach(a => { const d = Math.hypot(a.x, a.y, a.z); if (d > maxDist) maxDist = d; });
    if (data.cell && pack !== 'asym') {
      const m = data.cell.m;
      const dx = m[0][0]*rep[0] + m[0][1]*rep[1] + m[0][2]*rep[2];
      const dy = m[1][1]*rep[1] + m[1][2]*rep[2];
      const dz = m[2][2]*rep[2];
      maxDist = Math.max(maxDist, Math.hypot(dx, dy, dz) / 2);
    }
    stateRef.current.zoomDist = Math.max(maxDist * 2.5, 8);
    stateRef.current.rotX = 0; stateRef.current.rotY = 0;
    stateRef.current.panX = 0; stateRef.current.panY = 0;

    // ---- shared geometry / material caches --------------------------------
    const geomCache: Record<string, THREE.SphereGeometry> = {};
    const getSphere = (r: number) => {
      const k = r.toFixed(3);
      if (!geomCache[k]) geomCache[k] = new THREE.SphereGeometry(r, 20, 16);
      return geomCache[k];
    };
    const matCache: Record<string, THREE.MeshPhongMaterial> = {};
    const getMat = (color: number) => {
      const k = String(color);
      if (!matCache[k]) matCache[k] = new THREE.MeshPhongMaterial({ color, shininess: 80, specular: 0x444444 });
      return matCache[k];
    };

    // ---- atoms -----------------------------------------------------------
    atoms.forEach(atom => {
      const ad = getAtomData(atom.element);
      let r: number;
      if (style === 'spacefill') r = ad.radius * 1.7;
      else if (style === 'wireframe') r = radius * 0.3;
      else if (style === 'stick') r = 0.12;
      else r = Math.max(0.15, ad.radius * radius);
      const mesh = new THREE.Mesh(getSphere(r), getMat(ad.color));
      mesh.position.set(atom.x, atom.y, atom.z);
      mesh.userData = { element: atom.element, name: ad.name };
      mesh.castShadow = true;
      group.add(mesh);
      atomMeshesRef.current.push(mesh);
    });

    // ---- covalent bonds (covalent-radius rule, spatial hash) --------------
    const bondsOfAtom: Record<number, number[]> = {};

    if (style !== 'spacefill') {
      const CELL = 3.0;
      const grid: Record<string, number[]> = {};
      const gkey = (i: number, j: number, k: number) => `${i},${j},${k}`;
      atoms.forEach((a, idx) => {
        const k = gkey(Math.floor(a.x / CELL), Math.floor(a.y / CELL), Math.floor(a.z / CELL));
        (grid[k] || (grid[k] = [])).push(idx);
      });

      const rBond = style === 'stick' ? 0.12 : 0.08;
      const bondGeom = new THREE.CylinderGeometry(rBond, rBond, 1, 8);

      for (let i = 0; i < atoms.length; i++) {
        const ai = atoms[i];
        const gi = Math.floor(ai.x / CELL), gj = Math.floor(ai.y / CELL), gk = Math.floor(ai.z / CELL);
        for (let di = -1; di <= 1; di++)
          for (let dj = -1; dj <= 1; dj++)
            for (let dk = -1; dk <= 1; dk++) {
              const bucket = grid[gkey(gi + di, gj + dj, gk + dk)];
              if (!bucket) continue;
              for (const j of bucket) {
                if (j <= i) continue;
                const aj = atoms[j];
                const dist = Math.hypot(ai.x - aj.x, ai.y - aj.y, ai.z - aj.z);
                if (dist < 0.4) continue;
                const rmax = getAtomData(ai.element).radius + getAtomData(aj.element).radius + tol;
                if (dist > rmax) continue;
                if (ai.element === 'H' && aj.element === 'H') continue;

                (bondsOfAtom[i] || (bondsOfAtom[i] = [])).push(j);
                (bondsOfAtom[j] || (bondsOfAtom[j] = [])).push(i);

                if (!bondsOn) continue;

                if (style === 'wireframe') {
                  const pts = [
                    new THREE.Vector3(ai.x, ai.y, ai.z),
                    new THREE.Vector3(aj.x, aj.y, aj.z),
                  ];
                  group.add(new THREE.Line(
                    new THREE.BufferGeometry().setFromPoints(pts),
                    new THREE.LineBasicMaterial({ color: 0x888888 }),
                  ));
                } else {
                  const mid = new THREE.Vector3((ai.x+aj.x)/2, (ai.y+aj.y)/2, (ai.z+aj.z)/2);
                  const dir = new THREE.Vector3(aj.x-ai.x, aj.y-ai.y, aj.z-ai.z).normalize();
                  const halfLen = dist / 2;
                  [ai, aj].forEach((atom, side) => {
                    const halfMid = new THREE.Vector3(
                      (atom.x + mid.x) / 2, (atom.y + mid.y) / 2, (atom.z + mid.z) / 2,
                    );
                    const bMesh = new THREE.Mesh(bondGeom, getMat(getAtomData(atom.element).color));
                    bMesh.position.copy(halfMid);
                    bMesh.scale.set(1, halfLen, 1);
                    bMesh.quaternion.setFromUnitVectors(
                      new THREE.Vector3(0, 1, 0),
                      side === 0 ? dir : dir.clone().negate(),
                    );
                    group.add(bMesh);
                  });
                }
              }
            }
      }
    }

    // ---- hydrogen bonds (dashed cyan) ------------------------------------
    let hb = 0;
    if (hbondsOn && hydrogensOn) {
      const hbMat = new THREE.LineDashedMaterial({
        color: 0x66ddff, dashSize: 0.22, gapSize: 0.16, transparent: true, opacity: 0.85,
      });
      for (let h = 0; h < atoms.length; h++) {
        if (atoms[h].element !== 'H') continue;
        const donors = (bondsOfAtom[h] || []).filter(i => HBOND_ELEMENTS.has(atoms[i].element));
        if (!donors.length) continue;
        const donor = donors[0];
        for (let acc = 0; acc < atoms.length; acc++) {
          if (acc === donor || acc === h) continue;
          if (!HBOND_ELEMENTS.has(atoms[acc].element)) continue;
          const d = Math.hypot(
            atoms[h].x - atoms[acc].x,
            atoms[h].y - atoms[acc].y,
            atoms[h].z - atoms[acc].z,
          );
          if (d < 1.4 || d > 2.6) continue;
          // require a reasonably linear D-H...A arrangement
          const v1 = new THREE.Vector3(
            atoms[donor].x - atoms[h].x, atoms[donor].y - atoms[h].y, atoms[donor].z - atoms[h].z,
          ).normalize();
          const v2 = new THREE.Vector3(
            atoms[acc].x - atoms[h].x, atoms[acc].y - atoms[h].y, atoms[acc].z - atoms[h].z,
          ).normalize();
          if (v1.dot(v2) > -0.5) continue;
          const g = new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(atoms[h].x, atoms[h].y, atoms[h].z),
            new THREE.Vector3(atoms[acc].x, atoms[acc].y, atoms[acc].z),
          ]);
          const line = new THREE.Line(g, hbMat);
          line.computeLineDistances();
          group.add(line);
          hb++;
        }
      }
    }
    setHbondCount(hb);

    // ---- unit cell box + axes -------------------------------------------
    if (data.cell && (cellOn || axesOn)) {
      const m = data.cell.m;
      const toCart = (fx: number, fy: number, fz: number) => new THREE.Vector3(
        m[0][0]*fx + m[0][1]*fy + m[0][2]*fz - cx,
        m[1][1]*fy + m[1][2]*fz - cy,
        m[2][2]*fz - cz,
      );
      const repX = pack === 'super' ? rx : 1;
      const repY = pack === 'super' ? ry : 1;
      const repZ = pack === 'super' ? rz : 1;

      if (cellOn) {
        const faint  = new THREE.LineBasicMaterial({ color: 0x4488ff, transparent: true, opacity: 0.28 });
        const strong = new THREE.LineBasicMaterial({ color: 0x4488ff, transparent: true, opacity: 0.85 });
        const edges: [number[], number[]][] = [
          [[0,0,0],[1,0,0]], [[0,0,0],[0,1,0]], [[0,0,0],[0,0,1]],
          [[1,0,0],[1,1,0]], [[1,0,0],[1,0,1]], [[0,1,0],[1,1,0]],
          [[0,1,0],[0,1,1]], [[0,0,1],[1,0,1]], [[0,0,1],[0,1,1]],
          [[1,1,0],[1,1,1]], [[1,0,1],[1,1,1]], [[0,1,1],[1,1,1]],
        ];
        for (let i = 0; i < repX; i++)
          for (let j = 0; j < repY; j++)
            for (let k = 0; k < repZ; k++) {
              const isOrigin = i === 0 && j === 0 && k === 0;
              edges.forEach(([p, q]) => {
                const pts = [
                  toCart(p[0]+i, p[1]+j, p[2]+k),
                  toCart(q[0]+i, q[1]+j, q[2]+k),
                ];
                group.add(new THREE.Line(
                  new THREE.BufferGeometry().setFromPoints(pts),
                  isOrigin ? strong : faint,
                ));
              });
            }
      }

      if (axesOn) {
        const origin = toCart(0, 0, 0);
        const axes: [string, [number, number, number], number][] = [
          ['a', [1, 0, 0], 0xff4444],
          ['b', [0, 1, 0], 0x44ff44],
          ['c', [0, 0, 1], 0x4488ff],
        ];
        axes.forEach(([name, f, color]) => {
          const end = toCart(f[0], f[1], f[2]);
          group.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([origin, end]),
            new THREE.LineBasicMaterial({ color }),
          ));
          const label = makeLabel(name, '#' + color.toString(16).padStart(6, '0'));
          const dir = end.clone().sub(origin).normalize().multiplyScalar(0.9);
          label.position.copy(end).add(dir);
          group.add(label);
        });
      }
    }

    // ---- sidebar stats ---------------------------------------------------
    setAtomCount(atoms.length);
    setCellParams(data.cell?.params || null);
    const elMap: Record<string, number> = {};
    atoms.forEach(a => { elMap[a.element] = (elMap[a.element] || 0) + 1; });
    setElements(
      Object.entries(elMap)
        .sort((p, q) => q[1] - p[1])
        .map(([el, count]) => ({
          el, count,
          color: '#' + getAtomData(el).color.toString(16).padStart(6, '0'),
        })),
    );
  }, []);

  // Regenerate the displayed structure from the raw parse, then draw it
  const refresh = useCallback(() => {
    const raw = rawDataRef.current;
    if (!raw) return;
    const derived = deriveStructure(raw, packing, nx, ny, nz, showH);
    buildScene(
      derived, displayStyle, atomRadius, bondTol,
      showCell, showBonds, showHBonds, showAxes, showH,
      packing, nx, ny, nz,
    );
  }, [
    buildScene, packing, nx, ny, nz, showH, displayStyle,
    atomRadius, bondTol, showCell, showBonds, showHBonds, showAxes,
  ]);

  const loadStructure = useCallback((raw: StructureData) => {
    rawDataRef.current = raw;
    setSymOpCount(raw.symOps.length);
    setHasCell(!!raw.cell);
    if (!raw.cell) setPacking('asym');
    else setPacking(p => (p === 'asym' ? 'cell' : p));
  }, []);

  // -------------------------------------------------------------------------
  // Init THREE renderer
  // -------------------------------------------------------------------------
  useEffect(() => {
    if (!isOpen || !canvasRef.current) return;

    const canvas = canvasRef.current;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0d1117);
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.01, 2000);
    camera.position.set(0, 0, 20);
    cameraRef.current = camera;

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const dir1 = new THREE.DirectionalLight(0xffffff, 0.9);
    dir1.position.set(10, 15, 10);
    dir1.castShadow = true;
    scene.add(dir1);
    const dir2 = new THREE.DirectionalLight(0x8888ff, 0.3);
    dir2.position.set(-10, -5, -10);
    scene.add(dir2);
    const pt = new THREE.PointLight(0xffffff, 0.4, 200);
    pt.position.set(0, 10, 0);
    scene.add(pt);

    const group = new THREE.Group();
    scene.add(group);
    groupRef.current = group;

    const resize = () => {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (w && h) {
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const raycaster = new THREE.Raycaster();
    const mouse2d = new THREE.Vector2(999, 999);

    const animate = () => {
      animFrameRef.current = requestAnimationFrame(animate);
      const st = stateRef.current;
      if (st.spinning) st.rotY += 0.005;
      group.rotation.x = st.rotX;
      group.rotation.y = st.rotY;
      group.position.x = st.panX;
      group.position.y = st.panY;
      camera.position.z = st.zoomDist;

      raycaster.setFromCamera(mouse2d, camera);
      const hits = raycaster.intersectObjects(atomMeshesRef.current);
      if (hits.length) {
        const d = hits[0].object.userData as { element: string; name: string };
        setHoverLabel(`${d.name} (${d.element})`);
      } else {
        setHoverLabel('');
      }

      renderer.render(scene, camera);
    };
    animate();

    const onMouseDown = (e: MouseEvent) => {
      stateRef.current.isDragging = true;
      stateRef.current.isRightDrag = e.button === 2;
      stateRef.current.prevMouse = { x: e.clientX, y: e.clientY };
    };
    const onMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      mouse2d.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse2d.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      const st = stateRef.current;
      if (!st.isDragging) return;
      const dx = e.clientX - st.prevMouse.x;
      const dy = e.clientY - st.prevMouse.y;
      if (st.isRightDrag) {
        st.panX += dx * 0.02;
        st.panY -= dy * 0.02;
      } else {
        st.rotY += dx * 0.008;
        st.rotX += dy * 0.008;
      }
      st.prevMouse = { x: e.clientX, y: e.clientY };
    };
    const onMouseUp = () => { stateRef.current.isDragging = false; };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      stateRef.current.zoomDist = Math.max(2, Math.min(600, stateRef.current.zoomDist + e.deltaY * 0.05));
    };
    const onContextMenu = (e: Event) => e.preventDefault();

    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('mouseleave', onMouseUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('contextmenu', onContextMenu);

    // Load from props if provided
    try {
      if (cifContent) loadStructure(parseCIF(cifContent));
      else if (pdbContent) loadStructure(parsePDB(pdbContent));
    } catch {
      setError('Failed to parse structure.');
    }

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      ro.disconnect();
      canvas.removeEventListener('mousedown', onMouseDown);
      canvas.removeEventListener('mousemove', onMouseMove);
      canvas.removeEventListener('mouseup', onMouseUp);
      canvas.removeEventListener('mouseleave', onMouseUp);
      canvas.removeEventListener('wheel', onWheel);
      canvas.removeEventListener('contextmenu', onContextMenu);
      renderer.dispose();
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      groupRef.current = null;
    };
  }, [isOpen, cifContent, pdbContent, loadStructure]);

  // Redraw whenever any display option changes
  useEffect(() => {
    if (isOpen) refresh();
  }, [isOpen, refresh]);

  useEffect(() => { stateRef.current.spinning = spinning; }, [spinning]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true); setError(null);
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const text = ev.target?.result as string;
        const name = file.name.toLowerCase();
        if (name.endsWith('.cif')) loadStructure(parseCIF(text));
        else if (name.endsWith('.pdb')) loadStructure(parsePDB(text));
        else loadStructure(parseXYZ(text));
      } catch {
        setError('Failed to parse file. Check format.');
      }
      setLoading(false);
    };
    reader.readAsText(file);
  };

  const handleReset = () => {
    stateRef.current.rotX = 0; stateRef.current.rotY = 0;
    stateRef.current.panX = 0; stateRef.current.panY = 0;
    const atoms = displayDataRef.current?.atoms;
    if (atoms?.length) {
      let maxDist = 0;
      atoms.forEach(a => { const d = Math.hypot(a.x, a.y, a.z); if (d > maxDist) maxDist = d; });
      stateRef.current.zoomDist = Math.max(maxDist * 2.5, 8);
    }
  };

  if (!isOpen) return null;

  // -------------------------------------------------------------------------
  // Styles
  // -------------------------------------------------------------------------
  const sectionLabel: React.CSSProperties = {
    fontSize: 10, color: '#6b7280', margin: '0 0 6px',
    textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600,
  };
  const sectionBox: React.CSSProperties = { borderTop: '1px solid #1f2937', paddingTop: 12 };
  const rowLabel = (active: boolean): React.CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
    color: active ? '#60a5fa' : '#d1d5db', cursor: 'pointer', marginBottom: 4,
  });
  const btn = (active?: boolean): React.CSSProperties => ({
    padding: '6px 12px', borderRadius: 8, border: '1px solid #374151',
    background: active ? '#1e3a5f' : 'transparent',
    color: active ? '#60a5fa' : '#9ca3af', cursor: 'pointer', fontSize: 13,
  });
  const chip = (bg: string, fg: string): React.CSSProperties => ({
    fontSize: 12, padding: '2px 10px', borderRadius: 99, background: bg, color: fg,
  });

  const packingDisabled = !hasCell;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: '#111827', borderRadius: 16, width: '94vw', maxWidth: 1240, height: '90vh', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 60px rgba(0,0,0,0.7)', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid #1f2937' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: '#f9fafb' }}>
              Crystal 3D Viewer {pmc_id ? `— ${pmc_id}` : ''}
            </span>
            {atomCount > 0 && <span style={chip('#1e3a5f', '#60a5fa')}>{atomCount} atoms</span>}
            {symOpCount > 0 && <span style={chip('#3b2a5f', '#c4b5fd')}>{symOpCount} sym ops</span>}
            {hbondCount > 0 && <span style={chip('#164e63', '#67e8f9')}>{hbondCount} H-bonds</span>}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={handleReset} style={btn()}>↺ Reset view</button>
            <button onClick={() => setSpinning(s => !s)} style={btn(spinning)}>⟳ Spin</button>
            <button onClick={onClose} style={{ ...btn(), fontSize: 18, lineHeight: 1 }}>✕</button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

          {/* Canvas */}
          <div style={{ flex: 1, position: 'relative' }}>
            {loading && (
              <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10 }}>
                <span style={{ color: '#fff', fontSize: 16 }}>Loading...</span>
              </div>
            )}
            {error && (
              <div style={{ position: 'absolute', top: 16, left: '50%', transform: 'translateX(-50%)', background: '#7f1d1d', color: '#fca5a5', padding: '8px 16px', borderRadius: 8, fontSize: 13, zIndex: 10 }}>
                {error}
              </div>
            )}
            <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block', cursor: 'grab' }} />
            {hoverLabel && (
              <div style={{ position: 'absolute', bottom: 12, left: 12, background: 'rgba(0,0,0,0.7)', color: '#60a5fa', padding: '4px 10px', borderRadius: 6, fontSize: 13, fontWeight: 500 }}>
                {hoverLabel}
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div style={{ width: 214, borderLeft: '1px solid #1f2937', background: '#0d1117', padding: 14, display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>

            {/* Packing */}
            <div>
              <p style={sectionLabel}>Packing</p>
              {([
                ['asym',  'Asymmetric unit'],
                ['cell',  'Unit cell'],
                ['super', 'Supercell'],
              ] as [Packing, string][]).map(([val, label]) => {
                const disabled = packingDisabled && val !== 'asym';
                return (
                  <label
                    key={val}
                    style={{
                      ...rowLabel(packing === val),
                      opacity: disabled ? 0.4 : 1,
                      cursor: disabled ? 'not-allowed' : 'pointer',
                    }}
                  >
                    <input
                      type="radio" name="packing" value={val}
                      checked={packing === val}
                      disabled={disabled}
                      onChange={() => setPacking(val)}
                    />
                    {label}
                  </label>
                );
              })}

              {packing === 'super' && (
                <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                  {([[nx, setNx, 'a'], [ny, setNy, 'b'], [nz, setNz, 'c']] as [number, (n: number) => void, string][]).map(([v, set, ax]) => (
                    <div key={ax} style={{ flex: 1 }}>
                      <p style={{ fontSize: 9, color: '#6b7280', margin: '0 0 2px', textAlign: 'center' }}>{ax}</p>
                      <input
                        type="number" min={1} max={4} value={v}
                        onChange={e => set(Math.max(1, Math.min(4, parseInt(e.target.value) || 1)))}
                        style={{ width: '100%', background: '#111827', border: '1px solid #374151', borderRadius: 6, color: '#d1d5db', fontSize: 12, padding: '3px 4px', textAlign: 'center' }}
                      />
                    </div>
                  ))}
                </div>
              )}

              {packingDisabled && (
                <p style={{ fontSize: 10, color: '#6b7280', margin: '6px 0 0', lineHeight: 1.4 }}>
                  No unit cell in this file
                </p>
              )}
              {!packingDisabled && symOpCount === 0 && (
                <p style={{ fontSize: 10, color: '#a16207', margin: '6px 0 0', lineHeight: 1.4 }}>
                  No symmetry ops in CIF — showing P1 contents only
                </p>
              )}
            </div>

            {/* Load file */}
            <div style={sectionBox}>
              <p style={sectionLabel}>Load file</p>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 10px', border: '1px dashed #374151', borderRadius: 8, cursor: 'pointer', fontSize: 12, color: '#9ca3af' }}>
                ↑ CIF / PDB / XYZ
                <input type="file" accept=".cif,.pdb,.xyz" onChange={handleFileUpload} style={{ display: 'none' }} />
              </label>
            </div>

            {/* Style */}
            <div style={sectionBox}>
              <p style={sectionLabel}>Display style</p>
              {(['ball-stick', 'spacefill', 'wireframe', 'stick'] as DisplayStyle[]).map(s => (
                <label key={s} style={rowLabel(displayStyle === s)}>
                  <input type="radio" name="style" value={s} checked={displayStyle === s} onChange={() => setDisplayStyle(s)} />
                  {s.charAt(0).toUpperCase() + s.slice(1).replace('-', ' & ')}
                </label>
              ))}
            </div>

            {/* Options */}
            <div style={sectionBox}>
              <p style={sectionLabel}>Options</p>
              {([
                ['Unit cell box', showCell, setShowCell],
                ['Cell axes a/b/c', showAxes, setShowAxes],
                ['Bonds', showBonds, setShowBonds],
                ['Hydrogen bonds', showHBonds, setShowHBonds],
                ['Show hydrogens', showH, setShowH],
              ] as [string, boolean, (v: boolean) => void][]).map(([label, val, set]) => (
                <label key={label} style={rowLabel(false)}>
                  <input type="checkbox" checked={val} onChange={e => set(e.target.checked)} />
                  {label}
                </label>
              ))}
            </div>

            {/* Atom size */}
            <div style={sectionBox}>
              <p style={sectionLabel}>Atom size</p>
              <input type="range" min={0.15} max={1.0} step={0.05} value={atomRadius}
                     onChange={e => setAtomRadius(parseFloat(e.target.value))} style={{ width: '100%' }} />
              <p style={{ fontSize: 11, color: '#6b7280', margin: '2px 0 0', textAlign: 'right' }}>{atomRadius.toFixed(2)}</p>
            </div>

            {/* Bond tolerance */}
            <div style={sectionBox}>
              <p style={sectionLabel}>Bond tolerance</p>
              <input type="range" min={0.1} max={0.8} step={0.05} value={bondTol}
                     onChange={e => setBondTol(parseFloat(e.target.value))} style={{ width: '100%' }} />
              <p style={{ fontSize: 11, color: '#6b7280', margin: '2px 0 0', textAlign: 'right' }}>+{bondTol.toFixed(2)} Å</p>
              <p style={{ fontSize: 10, color: '#4b5563', margin: '4px 0 0', lineHeight: 1.4 }}>
                Bonded when d &lt; r₁ + r₂ + tol
              </p>
            </div>

            {/* Legend */}
            {elements.length > 0 && (
              <div style={sectionBox}>
                <p style={sectionLabel}>Elements</p>
                {elements.map(({ el, color, count }) => (
                  <div key={el} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#d1d5db', marginBottom: 4 }}>
                    <span style={{ width: 10, height: 10, borderRadius: '50%', background: color, display: 'inline-block', flexShrink: 0 }} />
                    {el}
                    <span style={{ marginLeft: 'auto', color: '#6b7280' }}>{count}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Cell params */}
            {cellParams && (
              <div style={sectionBox}>
                <p style={sectionLabel}>Cell parameters</p>
                {[
                  `a = ${cellParams.a.toFixed(3)} Å`,
                  `b = ${cellParams.b.toFixed(3)} Å`,
                  `c = ${cellParams.c.toFixed(3)} Å`,
                  `α = ${cellParams.alpha.toFixed(1)}°`,
                  `β = ${cellParams.beta.toFixed(1)}°`,
                  `γ = ${cellParams.gamma.toFixed(1)}°`,
                ].map(s => (
                  <p key={s} style={{ fontSize: 11, color: '#9ca3af', margin: '2px 0', fontFamily: 'monospace' }}>{s}</p>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div style={{ padding: '8px 20px', borderTop: '1px solid #1f2937', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <p style={{ fontSize: 11, color: '#6b7280', margin: 0 }}>
            Drag to rotate · Scroll to zoom · Right-drag to pan
          </p>
          <span style={{ fontSize: 11, color: '#60a5fa', fontWeight: 500 }}>{hoverLabel}</span>
        </div>
      </div>
    </div>
  );
}