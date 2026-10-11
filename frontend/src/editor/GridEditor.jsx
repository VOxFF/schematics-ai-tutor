// Grid editor: renders the board with three.js (orthographic, top-down) and HTML labels via
// CSS2DRenderer; every element is its own scene node (scene.js). While an inventory item is
// dragged over it, it shows a ghost with blue/red target points and places the item on drop.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { plan } from "./placement.js";
import { boardBounds, buildBoard, disposeTree, previewNode } from "./scene.js";
import { CELL, STYLE } from "./style.js";

const MARGIN = 1.04; // a little air around the grid

export default function GridEditor({ board, readings, drag, onDrop, onPlan }) {
  const host = useRef(null);
  const view = useRef(null);
  const pointer = useRef(null); // last grid point under the pointer while dragging
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

  // Grid point under a pointer event, or null outside the editor.
  const pointAt = (event) => {
    const state = view.current;
    const rect = host.current?.getBoundingClientRect();
    if (!state || !rect) return null;
    const ndc = new THREE.Vector3(((event.clientX - rect.left) / rect.width) * 2 - 1,
                                  -((event.clientY - rect.top) / rect.height) * 2 + 1, 0);
    const world = ndc.unproject(state.camera);
    return [Math.round(world.x / CELL), Math.round(-world.y / CELL)];
  };

  // Ghost preview for the dragged item at the last pointer position.
  useEffect(() => {
    const state = view.current;
    if (!state) return;
    if (state.preview) {
      state.scene.remove(state.preview);
      disposeTree(state.preview);
      state.preview = null;
    }
    if (drag && pointer.current && board) {
      const planned = plan(board, drag.item, pointer.current, drag.rotation);
      state.preview = previewNode(drag.item, planned, drag.rotation);
      state.scene.add(state.preview);
      onPlan?.(planned.valid);
    } else {
      onPlan?.(null);
    }
    state.render();
  });

  const [, redraw] = useState(0);
  const move = (event) => {
    if (!drag) return;
    const point = pointAt(event);
    const previous = pointer.current;
    if (point && (!previous || point[0] !== previous[0] || point[1] !== previous[1])) {
      pointer.current = point;
      redraw((n) => n + 1);
    }
  };
  const leave = () => {
    if (drag && pointer.current) {
      pointer.current = null;
      redraw((n) => n + 1);
    }
  };
  const drop = (event) => {
    if (!drag) return;
    const point = pointAt(event);
    pointer.current = null;
    if (point) {
      event.stopPropagation(); // handled here; the screen-level handler would cancel
      onDrop?.(point);
    }
  };

  if (unsupported) return <p className="muted">The grid needs WebGL, which isn't available here.</p>;
  return (
    <div
      ref={host}
      className={`grid-editor${drag ? " dragging" : ""}`}
      aria-label="Grid"
      onPointerMove={move}
      onPointerLeave={leave}
      onPointerUp={drop}
    />
  );
}
