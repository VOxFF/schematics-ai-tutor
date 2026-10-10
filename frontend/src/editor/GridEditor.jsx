// Grid editor, step 1: renders the board with three.js (orthographic, top-down) and HTML
// labels via CSS2DRenderer. Every element is its own scene node (see scene.js).
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { boardBounds, buildBoard, disposeTree } from "./scene.js";
import { STYLE } from "./style.js";

const MARGIN = 1.04; // a little air around the grid

export default function GridEditor({ board, readings }) {
  const host = useRef(null);
  const view = useRef(null);
  const [unsupported, setUnsupported] = useState(false);

  // Renderer, camera and resize handling: created once.
  useEffect(() => {
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setUnsupported(true); // no WebGL (e.g. test environments)
      return undefined;
    }
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setClearColor(STYLE.canvas.background);
    const labels = new CSS2DRenderer();
    labels.domElement.className = "editor-labels";
    host.current.append(renderer.domElement, labels.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -10, 10);
    const state = { renderer, labels, scene, camera, root: null, bounds: null };

    state.render = () => {
      renderer.render(scene, camera);
      labels.render(scene, camera);
    };
    // Fit the grid into the panel, keeping square cells.
    state.fit = () => {
      const { clientWidth: width, clientHeight: height } = host.current;
      if (!width || !height || !state.bounds) return;
      renderer.setSize(width, height);
      labels.setSize(width, height);
      const b = state.bounds;
      const cx = (b.left + b.right) / 2;
      const cy = (b.top + b.bottom) / 2;
      const scale = Math.max(((b.right - b.left) * MARGIN) / width, ((b.top - b.bottom) * MARGIN) / height);
      camera.left = cx - (width * scale) / 2;
      camera.right = cx + (width * scale) / 2;
      camera.top = cy + (height * scale) / 2;
      camera.bottom = cy - (height * scale) / 2;
      camera.updateProjectionMatrix();
      state.render();
    };

    const observer = new ResizeObserver(() => state.fit());
    observer.observe(host.current);
    view.current = state;
    return () => {
      observer.disconnect();
      if (state.root) disposeTree(state.root);
      renderer.dispose();
      renderer.domElement.remove();
      labels.domElement.remove();
      view.current = null;
    };
  }, []);

  // Rebuild the board's scene graph when the board or the readings change.
  useEffect(() => {
    const state = view.current;
    if (!state || !board) return;
    if (state.root) {
      state.scene.remove(state.root);
      disposeTree(state.root);
    }
    state.root = buildBoard(board, readings ?? {});
    state.scene.add(state.root);
    state.bounds = boardBounds(board);
    state.fit();
  }, [board, readings, unsupported]);

  if (unsupported) return <p className="muted">The grid needs WebGL, which isn't available here.</p>;
  return <div ref={host} className="grid-editor" aria-label="Grid" />;
}
