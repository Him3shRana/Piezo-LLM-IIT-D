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
// Atom data
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

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Atom { element: string; x: number; y: number; z: number; }
interface CellVecs {
  a: [number, number, number];
  b: [number, number, number];
  c: [number, number, number];
  params: { a: number; b: number; c: number; alpha: number; beta: number; gamma: number };
}
interface StructureData { atoms: Atom[]; cell: CellVecs | null; }

// ---------------------------------------------------------------------------
// Parsers
// ---------------------------------------------------------------------------
function parseCIF(text: string): StructureData {
  const lines = text.split('\n');
  let a = 1, b = 1, c = 1, alpha = 90, beta = 90, gamma = 90;
  const atomList: { element: string; fx: number; fy: number; fz: number }[] = [];
  let headers: string[] = [], inAtomSite = false;
  const colMap: Record<string, number> = {};

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('#')) continue;

    const aM = line.match(/_cell_length_a\s+([\d.]+)/);
    const bM = line.match(/_cell_length_b\s+([\d.]+)/);
    const cM = line.match(/_cell_length_c\s+([\d.]+)/);
    const alM = line.match(/_cell_angle_alpha\s+([\d.]+)/);
    const beM = line.match(/_cell_angle_beta\s+([\d.]+)/);
    const gaM = line.match(/_cell_angle_gamma\s+([\d.]+)/);
    if (aM) a = parseFloat(aM[1]);
    if (bM) b = parseFloat(bM[1]);
    if (cM) c = parseFloat(cM[1]);
    if (alM) alpha = parseFloat(alM[1]);
    if (beM) beta = parseFloat(beM[1]);
    if (gaM) gamma = parseFloat(gaM[1]);

    if (line === 'loop_') { headers = []; inAtomSite = false; Object.keys(colMap).forEach(k => delete colMap[k]); continue; }

    if (line.startsWith('_atom_site_')) {
      inAtomSite = true;
      colMap[line] = headers.length;
      headers.push(line);
      continue;
    }

    if (inAtomSite && !line.startsWith('_') && line.length > 0) {
      const parts = line.split(/\s+/);
      const xKey = Object.keys(colMap).find(k => k.includes('fract_x'));
      const yKey = Object.keys(colMap).find(k => k.includes('fract_y'));
      const zKey = Object.keys(colMap).find(k => k.includes('fract_z'));
      const typeKey = Object.keys(colMap).find(k => k.includes('type_symbol') || k.includes('label'));
      if (xKey && yKey && zKey && typeKey) {
        const fx = parseFloat(parts[colMap[xKey]]);
        const fy = parseFloat(parts[colMap[yKey]]);
        const fz = parseFloat(parts[colMap[zKey]]);
        let el = parts[colMap[typeKey]].replace(/[0-9_+\-]/g, '');
        el = el.charAt(0).toUpperCase() + (el.charAt(1) || '').toLowerCase();
        if (!isNaN(fx) && !isNaN(fy) && !isNaN(fz)) atomList.push({ element: el, fx, fy, fz });
      }
    }
    if (inAtomSite && line.startsWith('_') && !line.startsWith('_atom_site_')) inAtomSite = false;
  }

  const toRad = (deg: number) => deg * Math.PI / 180;
  const cosA = Math.cos(toRad(alpha)), cosB = Math.cos(toRad(beta)), cosG = Math.cos(toRad(gamma));
  const sinG = Math.sin(toRad(gamma));
  const vol = a * b * c * Math.sqrt(1 - cosA*cosA - cosB*cosB - cosG*cosG + 2*cosA*cosB*cosG);
  const mat = [
    [a, b * cosG, c * cosB],
    [0, b * sinG, c * (cosA - cosB * cosG) / sinG],
    [0, 0, vol / (a * b * sinG)],
  ];

  const cartAtoms: Atom[] = atomList.map(at => ({
    element: at.element,
    x: mat[0][0]*at.fx + mat[0][1]*at.fy + mat[0][2]*at.fz,
    y: mat[1][1]*at.fy + mat[1][2]*at.fz,
    z: mat[2][2]*at.fz,
  }));

  const cell: CellVecs = {
    a: [mat[0][0], mat[1][0], mat[2][0]],
    b: [mat[0][1], mat[1][1], mat[2][1]],
    c: [mat[0][2], mat[1][2], mat[2][2]],
    params: { a, b, c, alpha, beta, gamma },
  };

  return { atoms: cartAtoms, cell };
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
  return { atoms, cell: null };
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
  return { atoms, cell: null };
}

function centerAtoms(atoms: Atom[]): Atom[] {
  if (!atoms.length) return atoms;
  const cx = atoms.reduce((s, a) => s + a.x, 0) / atoms.length;
  const cy = atoms.reduce((s, a) => s + a.y, 0) / atoms.length;
  const cz = atoms.reduce((s, a) => s + a.z, 0) / atoms.length;
  return atoms.map(a => ({ ...a, x: a.x - cx, y: a.y - cy, z: a.z - cz }));
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
type DisplayStyle = 'ball-stick' | 'spacefill' | 'wireframe' | 'stick';

export default function Crystal3DViewer({ pmc_id, isOpen, onClose, cifContent, pdbContent }: Crystal3DViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const groupRef = useRef<THREE.Group | null>(null);
  const animFrameRef = useRef<number>(0);
  const atomMeshesRef = useRef<THREE.Mesh[]>([]);
  const currentDataRef = useRef<StructureData | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [atomCount, setAtomCount] = useState(0);
  const [hoverLabel, setHoverLabel] = useState('');
  const [spinning, setSpinning] = useState(false);
  const [displayStyle, setDisplayStyle] = useState<DisplayStyle>('ball-stick');
  const [showCell, setShowCell] = useState(true);
  const [showBonds, setShowBonds] = useState(true);
  const [atomRadius, setAtomRadius] = useState(0.5);
  const [bondCutoff, setBondCutoff] = useState(2.0);
  const [cellParams, setCellParams] = useState<CellVecs['params'] | null>(null);
  const [elements, setElements] = useState<{ el: string; color: string; count: number }[]>([]);

  const stateRef = useRef({
    rotX: 0, rotY: 0, panX: 0, panY: 0, zoomDist: 20,
    isDragging: false, isRightDrag: false,
    prevMouse: { x: 0, y: 0 },
    spinning: false,
  });

  // Build THREE scene from structure data
  const buildScene = useCallback((data: StructureData, style: DisplayStyle, radius: number, cutoff: number, cell: boolean, bonds: boolean) => {
    const group = groupRef.current;
    const scene = sceneRef.current;
    if (!group || !scene) return;

    while (group.children.length) group.remove(group.children[0]);
    atomMeshesRef.current = [];

    const atoms = centerAtoms(data.atoms);
    currentDataRef.current = { ...data, atoms };

    let maxDist = 0;
    atoms.forEach(a => { const d = Math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z); if (d > maxDist) maxDist = d; });
    const zoom = Math.max(maxDist * 2.5, 8);
    stateRef.current.zoomDist = zoom;
    stateRef.current.rotX = 0; stateRef.current.rotY = 0;
    stateRef.current.panX = 0; stateRef.current.panY = 0;

    const geomCache: Record<string, THREE.SphereGeometry> = {};
    const getSphere = (r: number) => {
      const k = r.toFixed(3);
      if (!geomCache[k]) geomCache[k] = new THREE.SphereGeometry(r, 20, 16);
      return geomCache[k];
    };

    atoms.forEach(atom => {
      const ad = getAtomData(atom.element);
      let r = radius;
      if (style === 'spacefill') r = ad.radius * radius * 1.5;
      if (style === 'wireframe') r = radius * 0.15;
      const mat = new THREE.MeshPhongMaterial({ color: ad.color, shininess: 80, specular: 0x444444 });
      const mesh = new THREE.Mesh(getSphere(r), mat);
      mesh.position.set(atom.x, atom.y, atom.z);
      mesh.userData = { element: atom.element, name: ad.name };
      mesh.castShadow = true;
      group.add(mesh);
      atomMeshesRef.current.push(mesh);
    });

    if (bonds && style !== 'spacefill') {
      const bondGeom = new THREE.CylinderGeometry(0.06, 0.06, 1, 8);
      for (let i = 0; i < atoms.length; i++) {
        for (let j = i + 1; j < atoms.length; j++) {
          const dx = atoms[i].x - atoms[j].x;
          const dy = atoms[i].y - atoms[j].y;
          const dz = atoms[i].z - atoms[j].z;
          const dist = Math.sqrt(dx*dx+dy*dy+dz*dz);
          if (dist < cutoff && dist > 0.4) {
            if (style === 'wireframe') {
              const pts = [new THREE.Vector3(atoms[i].x, atoms[i].y, atoms[i].z), new THREE.Vector3(atoms[j].x, atoms[j].y, atoms[j].z)];
              const g = new THREE.BufferGeometry().setFromPoints(pts);
              const m = new THREE.LineBasicMaterial({ color: 0x888888 });
              group.add(new THREE.Line(g, m));
            } else {
              const mid = new THREE.Vector3((atoms[i].x+atoms[j].x)/2, (atoms[i].y+atoms[j].y)/2, (atoms[i].z+atoms[j].z)/2);
              const dir = new THREE.Vector3(atoms[j].x-atoms[i].x, atoms[j].y-atoms[i].y, atoms[j].z-atoms[i].z).normalize();
              const halfLen = dist / 2;
              [atoms[i], atoms[j]].forEach((atom, side) => {
                const halfMid = new THREE.Vector3(
                  (atom.x + mid.x) / 2, (atom.y + mid.y) / 2, (atom.z + mid.z) / 2
                );
                const bMat = new THREE.MeshPhongMaterial({ color: getAtomData(atom.element).color, shininess: 40 });
                const bMesh = new THREE.Mesh(bondGeom, bMat);
                bMesh.position.copy(halfMid);
                bMesh.scale.set(1, halfLen, 1);
                bMesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0), side === 0 ? dir : dir.clone().negate());
                group.add(bMesh);
              });
            }
          }
        }
      }
    }

    if (cell && data.cell) {
      const { a, b, c: cv } = data.cell;
      const vecs = [new THREE.Vector3(...a), new THREE.Vector3(...b), new THREE.Vector3(...cv)];
      const o = new THREE.Vector3(0,0,0);
      const corners = [
        o.clone(), vecs[0].clone(), vecs[1].clone(), vecs[2].clone(),
        vecs[0].clone().add(vecs[1]), vecs[0].clone().add(vecs[2]),
        vecs[1].clone().add(vecs[2]), vecs[0].clone().add(vecs[1]).add(vecs[2]),
      ];
      const cx2 = corners[7].x/2, cy2 = corners[7].y/2, cz2 = corners[7].z/2;
      const edges = [[0,1],[0,2],[0,3],[1,4],[1,5],[2,4],[2,6],[3,5],[3,6],[4,7],[5,7],[6,7]];
      const lMat = new THREE.LineBasicMaterial({ color: 0x4488ff, transparent: true, opacity: 0.8 });
      edges.forEach(([ai, bi]) => {
        const pts = [corners[ai].clone().sub(new THREE.Vector3(cx2,cy2,cz2)), corners[bi].clone().sub(new THREE.Vector3(cx2,cy2,cz2))];
        group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), lMat));
      });
    }

    setAtomCount(atoms.length);
    setCellParams(data.cell?.params || null);
    const elMap: Record<string, number> = {};
    atoms.forEach(a => { elMap[a.element] = (elMap[a.element] || 0) + 1; });
    setElements(Object.entries(elMap).map(([el, count]) => ({
      el, count,
      color: '#' + getAtomData(el).color.toString(16).padStart(6, '0'),
    })));
  }, []);

  // Init THREE renderer
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

    const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.01, 1000);
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
    const pt = new THREE.PointLight(0xffffff, 0.4, 100);
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
    const mouse2d = new THREE.Vector2();

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
      if (st.isRightDrag) { st.panX += dx * 0.02; st.panY -= dy * 0.02; }
      else { st.rotY += dx * 0.008; st.rotX += dy * 0.008; }
      st.prevMouse = { x: e.clientX, y: e.clientY };
    };
    const onMouseUp = () => { stateRef.current.isDragging = false; };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      stateRef.current.zoomDist = Math.max(2, Math.min(200, stateRef.current.zoomDist + e.deltaY * 0.05));
    };
    const onContextMenu = (e: Event) => e.preventDefault();

    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('mouseleave', onMouseUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('contextmenu', onContextMenu);

    // Load from props if provided
    if (cifContent) { try { buildScene(parseCIF(cifContent), 'ball-stick', 0.5, 2.0, true, true); } catch {}  }
    else if (pdbContent) { try { buildScene(parsePDB(pdbContent), 'ball-stick', 0.5, 2.0, true, true); } catch {} }

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
  }, [isOpen, cifContent, pdbContent, buildScene]);

  // Rebuild scene when display options change
  useEffect(() => {
    if (currentDataRef.current && groupRef.current && sceneRef.current) {
      buildScene(currentDataRef.current, displayStyle, atomRadius, bondCutoff, showCell, showBonds);
    }
  }, [displayStyle, atomRadius, bondCutoff, showCell, showBonds, buildScene]);

  // Sync spin state to ref
  useEffect(() => { stateRef.current.spinning = spinning; }, [spinning]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true); setError(null);
    const reader = new FileReader();
    reader.onload = ev => {
      try {
        const text = ev.target?.result as string;
        let data: StructureData;
        if (file.name.endsWith('.cif')) data = parseCIF(text);
        else if (file.name.endsWith('.pdb')) data = parsePDB(text);
        else data = parseXYZ(text);
        buildScene(data, displayStyle, atomRadius, bondCutoff, showCell, showBonds);
      } catch (err) {
        setError('Failed to parse file. Check format.');
      }
      setLoading(false);
    };
    reader.readAsText(file);
  };

  const handleReset = () => {
    stateRef.current.rotX = 0; stateRef.current.rotY = 0;
    stateRef.current.panX = 0; stateRef.current.panY = 0;
    if (currentDataRef.current) {
      const atoms = currentDataRef.current.atoms;
      let maxDist = 0;
      atoms.forEach(a => { const d = Math.sqrt(a.x*a.x+a.y*a.y+a.z*a.z); if (d > maxDist) maxDist = d; });
      stateRef.current.zoomDist = Math.max(maxDist * 2.5, 8);
    }
  };

  if (!isOpen) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ background: '#111827', borderRadius: 16, width: '92vw', maxWidth: 1100, height: '88vh', display: 'flex', flexDirection: 'column', boxShadow: '0 25px 60px rgba(0,0,0,0.7)', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', borderBottom: '1px solid #1f2937' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18, fontWeight: 600, color: '#f9fafb' }}>
              Crystal 3D Viewer {pmc_id ? `— ${pmc_id}` : ''}
            </span>
            {atomCount > 0 && (
              <span style={{ fontSize: 12, padding: '2px 10px', borderRadius: 99, background: '#1e3a5f', color: '#60a5fa' }}>
                {atomCount} atoms
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={handleReset}
              style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #374151', background: 'transparent', color: '#9ca3af', cursor: 'pointer', fontSize: 13 }}
            >
              ↺ Reset view
            </button>
            <button
              onClick={() => setSpinning(s => !s)}
              style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #374151', background: spinning ? '#1e3a5f' : 'transparent', color: spinning ? '#60a5fa' : '#9ca3af', cursor: 'pointer', fontSize: 13 }}
            >
              ⟳ Spin
            </button>
            <button
              onClick={onClose}
              style={{ padding: '6px 12px', borderRadius: 8, border: '1px solid #374151', background: 'transparent', color: '#9ca3af', cursor: 'pointer', fontSize: 18, lineHeight: 1 }}
            >
              ✕
            </button>
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
            <canvas
              ref={canvasRef}
              style={{ width: '100%', height: '100%', display: 'block', cursor: 'grab' }}
            />
            {hoverLabel && (
              <div style={{ position: 'absolute', bottom: 12, left: 12, background: 'rgba(0,0,0,0.7)', color: '#60a5fa', padding: '4px 10px', borderRadius: 6, fontSize: 13, fontWeight: 500 }}>
                {hoverLabel}
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div style={{ width: 200, borderLeft: '1px solid #1f2937', background: '#0d1117', padding: 14, display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>

            {/* Upload */}
            <div>
              <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Load file</p>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 10px', border: '1px dashed #374151', borderRadius: 8, cursor: 'pointer', fontSize: 12, color: '#9ca3af' }}>
                ↑ CIF / PDB / XYZ
                <input type="file" accept=".cif,.pdb,.xyz" onChange={handleFileUpload} style={{ display: 'none' }} />
              </label>
            </div>

            {/* Style */}
            <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
              <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Display style</p>
              {(['ball-stick', 'spacefill', 'wireframe', 'stick'] as DisplayStyle[]).map(s => (
                <label key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: displayStyle === s ? '#60a5fa' : '#d1d5db', cursor: 'pointer', marginBottom: 4 }}>
                  <input type="radio" name="style" value={s} checked={displayStyle === s} onChange={() => setDisplayStyle(s)} />
                  {s.charAt(0).toUpperCase() + s.slice(1).replace('-', ' & ')}
                </label>
              ))}
            </div>

            {/* Options */}
            <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
              <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Options</p>
              {[
                { label: 'Unit cell box', val: showCell, set: setShowCell },
                { label: 'Bonds', val: showBonds, set: setShowBonds },
              ].map(opt => (
                <label key={opt.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#d1d5db', cursor: 'pointer', marginBottom: 4 }}>
                  <input type="checkbox" checked={opt.val} onChange={e => opt.set(e.target.checked)} />
                  {opt.label}
                </label>
              ))}
            </div>

            {/* Atom radius */}
            <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
              <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Atom radius</p>
              <input type="range" min={0.2} max={1.5} step={0.05} value={atomRadius} onChange={e => setAtomRadius(parseFloat(e.target.value))} style={{ width: '100%' }} />
              <p style={{ fontSize: 11, color: '#6b7280', margin: '2px 0 0', textAlign: 'right' }}>{atomRadius.toFixed(2)}</p>
            </div>

            {/* Bond cutoff */}
            <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
              <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Bond cutoff</p>
              <input type="range" min={1.0} max={3.5} step={0.05} value={bondCutoff} onChange={e => setBondCutoff(parseFloat(e.target.value))} style={{ width: '100%' }} />
              <p style={{ fontSize: 11, color: '#6b7280', margin: '2px 0 0', textAlign: 'right' }}>{bondCutoff.toFixed(2)} Å</p>
            </div>

            {/* Legend */}
            {elements.length > 0 && (
              <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
                <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Elements</p>
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
              <div style={{ borderTop: '1px solid #1f2937', paddingTop: 12 }}>
                <p style={{ fontSize: 10, color: '#6b7280', margin: '0 0 6px', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>Cell parameters</p>
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