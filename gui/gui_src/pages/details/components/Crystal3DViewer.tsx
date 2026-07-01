import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface Crystal3DViewerProps {
  pmc_id: string;
  isOpen: boolean;
  onClose: () => void;
}

export default function Crystal3DViewer({ pmc_id, isOpen, onClose }: Crystal3DViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || !containerRef.current) return;

    const initViewer = async () => {
      try {
        setLoading(true);
        setError(null);

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x111827);
        sceneRef.current = scene;

        const width = containerRef.current?.clientWidth || 800;
        const height = containerRef.current?.clientHeight || 600;

        const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
        camera.position.z = 5;

        const renderer = new THREE.WebGLRenderer({ antialias: true });
        if (containerRef.current) {
          renderer.setSize(width, height);
          containerRef.current.appendChild(renderer.domElement);
        }
        rendererRef.current = renderer;

        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambientLight);

        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
        directionalLight.position.set(5, 5, 5);
        scene.add(directionalLight);

        const cifFilename = `${pmc_id}-gamma-glycine.cif`;
        const response = await fetch(`/database/cif/${cifFilename}`);
        if (!response.ok) throw new Error('Failed to load CIF file');
        const cifContent = await response.text();

        const atoms = parseCIF(cifContent);

        atoms.forEach((atom) => {
          const geometry = new THREE.SphereGeometry(0.3, 32, 32);
          const color = getAtomColor(atom.element);
          const material = new THREE.MeshPhongMaterial({ color });
          const sphere = new THREE.Mesh(geometry, material);
          sphere.position.set(atom.x, atom.y, atom.z);
          scene.add(sphere);
        });

        for (let i = 0; i < atoms.length; i++) {
          for (let j = i + 1; j < atoms.length; j++) {
            const dist = Math.sqrt(
              Math.pow(atoms[i].x - atoms[j].x, 2) +
              Math.pow(atoms[i].y - atoms[j].y, 2) +
              Math.pow(atoms[i].z - atoms[j].z, 2)
            );
            if (dist < 2) {
              const points = [
                new THREE.Vector3(atoms[i].x, atoms[i].y, atoms[i].z),
                new THREE.Vector3(atoms[j].x, atoms[j].y, atoms[j].z),
              ];
              const geometry = new THREE.BufferGeometry().setFromPoints(points);
              const material = new THREE.LineBasicMaterial({ color: 0x888888 });
              const line = new THREE.Line(geometry, material);
              scene.add(line);
            }
          }
        }

        let isDragging = false;
        let previousMousePosition = { x: 0, y: 0 };

        renderer.domElement.addEventListener('mousedown', (e) => {
          isDragging = true;
          previousMousePosition = { x: e.clientX, y: e.clientY };
        });

        renderer.domElement.addEventListener('mousemove', (e) => {
          if (isDragging) {
            const deltaX = e.clientX - previousMousePosition.x;
            const deltaY = e.clientY - previousMousePosition.y;
            scene.rotation.y += deltaX * 0.005;
            scene.rotation.x += deltaY * 0.005;
            previousMousePosition = { x: e.clientX, y: e.clientY };
          }
        });

        renderer.domElement.addEventListener('mouseup', () => {
          isDragging = false;
        });

        renderer.domElement.addEventListener('wheel', (e) => {
          e.preventDefault();
          camera.position.z += e.deltaY * 0.01;
        });

        const animate = () => {
          requestAnimationFrame(animate);
          renderer.render(scene, camera);
        };
        animate();

        setLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
        setLoading(false);
      }
    };

    initViewer();

    return () => {
      if (rendererRef.current && containerRef.current) {
        try {
          containerRef.current.removeChild(rendererRef.current.domElement);
        } catch (e) {
          // Element already removed
        }
        rendererRef.current.dispose();
      }
    };
  }, [isOpen, pmc_id]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-[#111827] rounded-2xl w-11/12 h-5/6 max-w-4xl shadow-2xl flex flex-col">
        <div className="flex justify-between items-center p-6 border-b border-gray-700">
          <h2 className="text-2xl font-bold text-white">
            3D Crystal Structure - {pmc_id}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white text-2xl font-bold"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 relative">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-50">
              <div className="text-white text-lg">Loading 3D model...</div>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-50">
              <div className="text-red-400 text-lg">Error: {error}</div>
            </div>
          )}
          <div ref={containerRef} className="w-full h-full" />
        </div>

        <div className="p-4 border-t border-gray-700 text-gray-400 text-sm">
          <p>🖱️ Drag to rotate | 🔄 Scroll to zoom</p>
        </div>
      </div>
    </div>
  );
}

function parseCIF(content: string) {
  const atoms: Array<{ element: string; x: number; y: number; z: number }> = [];

  const lines = content.split('\n');
  let inAtomSite = false;
  let xIdx = -1,
    yIdx = -1,
    zIdx = -1,
    labelIdx = -1;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();

    if (line.startsWith('loop_')) {
      inAtomSite = false;
    }

    if (line.startsWith('_atom_site_label')) {
      inAtomSite = true;
      const headers = [];
      for (let j = i; j < lines.length; j++) {
        if (lines[j].trim().startsWith('_atom_site_')) {
          headers.push(lines[j].trim());
        } else {
          break;
        }
      }
      labelIdx = headers.findIndex((h) => h.includes('label'));
      xIdx = headers.findIndex((h) => h.includes('fract_x'));
      yIdx = headers.findIndex((h) => h.includes('fract_y'));
      zIdx = headers.findIndex((h) => h.includes('fract_z'));
      i += headers.length - 1;
      continue;
    }

    if (inAtomSite && line && !line.startsWith('_')) {
      const parts = line.split(/\s+/);
      if (parts.length > Math.max(xIdx, yIdx, zIdx)) {
        const label = parts[labelIdx] || 'C';
        const element = label.replace(/[0-9]/g, '').substring(0, 2);
        atoms.push({
          element,
          x: parseFloat(parts[xIdx]) * 5 - 2.5,
          y: parseFloat(parts[yIdx]) * 5 - 2.5,
          z: parseFloat(parts[zIdx]) * 5 - 2.5,
        });
      }
    }
  }

  return atoms;
}

function getAtomColor(element: string): number {
  const colors: { [key: string]: number } = {
    H: 0xffffff,
    C: 0x909090,
    N: 0x3050f8,
    O: 0xff0d0d,
    S: 0xffff30,
    P: 0xff8000,
    F: 0x90e050,
    Cl: 0x1ff01f,
    Br: 0xa62929,
    I: 0x940094,
  };
  return colors[element] || 0xcccccc;
}