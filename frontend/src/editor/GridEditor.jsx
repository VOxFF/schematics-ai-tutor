// Grid editor: one three.js scene (orthographic, top-down) with the board and, to its right,
// the inventory region, so both share one scale by construction. HTML labels via
// CSS2DRenderer; every element is its own scene node (scene.js). Pressing an inventory slot
// starts a drag; over the grid a ghost shows blue/red target points, and a drop places it.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { plan } from "./placement.js";
import { boardBounds, buildBoard, disposeTree, floatingNode, inventoryNode, layoutInventory, previewNode, sceneBounds, slotAt } from "./scene.js";
import { CELL, STYLE } from "./style.js";

const MARGIN = 1.04; // a little air around the grid

// `startBoard` is the task's starting board: the scene's bounds (and so its scale) are computed
// from it once per task and never change while the learner edits `board`.
export default function GridEditor({ board, startBoard, readings, drag, onStartDrag, onDrop, onPlan }) {
  const capacity = startBoard?.inventory?.length ?? 0;
  const host = useRef(null);
  const view = useRef(null);
  const pointer = useRef(null); // last grid point under the pointer while dragging (null off the grid)
  const pointerWorld = useRef(null); // last world position while dragging, for the free-floating ghost
  const [unsupported, setUnsupported] = useState(false);
  const [hover, setHover] = useState(null); // inventory slot key under the pointer

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
    const state = { renderer, labels, scene, camera, root: null, inventory: null, layout: null, bounds: null,
                    gridBounds: null, inventoryOffset: 0 };

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
      const g = state.gridBounds;
      const cy = (b.top + b.bottom) / 2;
      const scale = Math.max(((b.right - b.left) * MARGIN) / width, ((b.top - b.bottom) * MARGIN) / height);
      // The inventory sits flush right; the grid is centered in the field left of it.
      const viewWidth = width * scale;
      const inventoryWidth = b.right - g.right;
      camera.left = (g.left + g.right) / 2 - (viewWidth - inventoryWidth) / 2;
      camera.right = camera.left + viewWidth;
      state.inventoryOffset = camera.right - b.right; // shifts the inventory column to the right edge
      if (state.inventory) state.inventory.position.x = state.inventoryOffset;
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
      if (state.inventory) disposeTree(state.inventory);
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
    state.layout = layoutInventory(board, capacity);
    state.render();
  }, [board, capacity, readings, unsupported]);

  // Scene bounds: once per task, from its starting board. The inventory column reserves the
  // starting inventory's rows, so its width and height never change during the task.
  useEffect(() => {
    const state = view.current;
    if (!state || !startBoard) return;
    state.bounds = sceneBounds(startBoard, layoutInventory(startBoard, capacity));
    state.gridBounds = boardBounds(startBoard);
    state.fit();
  }, [startBoard, capacity, unsupported]);

  // The inventory region; rebuilt when its contents or the hovered slot change.
  useEffect(() => {
    const state = view.current;
    if (!state || !state.layout) return;
    if (state.inventory) {
      state.scene.remove(state.inventory);
      disposeTree(state.inventory);
    }
    // A part being dragged leaves its slot at once; the slot closes up after the drop.
    const lifted = drag?.item.kind === "part" ? `part:${drag.item.id}` : null;
    state.inventory = inventoryNode(state.layout, drag ? null : hover, lifted);
    state.inventory.position.x = state.inventoryOffset;
    state.scene.add(state.inventory);
    state.render();
  }, [board, hover, drag, unsupported]);

  // World point under a pointer event.
  const worldAt = (event) => {
    const state = view.current;
    const rect = host.current?.getBoundingClientRect();
    if (!state || !rect) return null;
    const ndc = new THREE.Vector3(((event.clientX - rect.left) / rect.width) * 2 - 1,
                                  -((event.clientY - rect.top) / rect.height) * 2 + 1, 0);
    return ndc.unproject(state.camera);
  };
  // Grid point under a pointer event, or null when it isn't over the grid.
  const pointAt = (event) => {
    const world = worldAt(event);
    if (!world || !board) return null;
    const point = [Math.round(world.x / CELL), Math.round(-world.y / CELL)];
    const { columns, rows } = board.grid;
    return point[0] >= 1 && point[1] >= 1 && point[0] <= columns && point[1] <= rows ? point : null;
  };
  const slotUnder = (event) => {
    const world = worldAt(event);
    const state = view.current;
    return world && state?.layout ? slotAt(state.layout, world.x - state.inventoryOffset, world.y) : null;
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
      // Over the grid: snapped ghost with blue/red target points.
      const planned = plan(board, drag.item, pointer.current, drag.rotation);
      state.preview = previewNode(drag.item, planned, drag.rotation);
      state.scene.add(state.preview);
      onPlan?.(planned.valid);
    } else if (drag && pointerWorld.current) {
      // Anywhere else in the editor (e.g. still over the inventory): the ghost follows freely.
      const { x, y } = pointerWorld.current;
      state.preview = floatingNode(drag.item, drag.rotation, x, y);
      state.scene.add(state.preview);
      onPlan?.(null);
    } else {
      onPlan?.(null);
    }
    state.render();
  });

  const [, redraw] = useState(0);
  const move = (event) => {
    if (!drag) {
      setHover(slotUnder(event)?.key ?? null);
      return;
    }
    const point = pointAt(event);
    const previous = pointer.current;
    const changed = point ? !previous || point[0] !== previous[0] || point[1] !== previous[1] : true;
    pointerWorld.current = worldAt(event);
    if (changed) {
      pointer.current = point; // null off the grid: the ghost floats, and a release there snaps back
      redraw((n) => n + 1);
    }
  };
  const press = (event) => {
    const slot = slotUnder(event);
    if (slot) {
      event.preventDefault();
      setHover(null);
      pointerWorld.current = worldAt(event); // the ghost appears under the pointer at once
      pointer.current = null;
      onStartDrag?.(slot.item);
    }
  };
  const leave = () => {
    setHover(null);
    if (drag) {
      pointer.current = null;
      pointerWorld.current = null; // outside the editor: no ghost
      redraw((n) => n + 1);
    }
  };
  const drop = (event) => {
    if (!drag) return;
    const point = pointAt(event);
    pointer.current = null;
    pointerWorld.current = null;
    if (point) {
      event.stopPropagation(); // handled here; the screen-level handler would cancel
      onDrop?.(point);
    }
  };

  if (unsupported) return <p className="muted">The grid needs WebGL, which isn't available here.</p>;
  return (
    <div
      ref={host}
      className={`grid-editor${drag ? " dragging" : ""}${hover ? " over-item" : ""}`}
      aria-label="Grid"
      onPointerDown={press}
      onPointerMove={move}
      onPointerLeave={leave}
      onPointerUp={drop}
    />
  );
}
