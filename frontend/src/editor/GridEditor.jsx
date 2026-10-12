// Grid editor: one three.js scene (orthographic, top-down) with the board and, to its right,
// the inventory region, so both share one scale by construction. HTML labels via
// CSS2DRenderer; every element is its own scene node (scene.js). Pressing an inventory item
// starts a drag. A click (press and release without moving) on a board element selects it
// (blue outline); moving the pointer a few pixels instead turns the press into the same drag. A dragged item is held where it was grabbed
// (no jump to the pointer); over the grid a ghost shows blue/red target points, and a drop places it.
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { lift, plan } from "./placement.js";
import { boardBounds, buildBoard, disposeTree, floatingNode, drawHighlight, inventoryNode, layoutInventory, outline, pickAt,
         previewNode, sceneBounds, slotAnchor, toWorld } from "./scene.js";
import { EDITOR } from "../lib/build.js";
import { CELL, STYLE } from "./style.js";

const MARGIN = 1.04; // a little air around the grid
// Every task is fitted as if it were at least this big (config.yaml `editor`: by default a 12 x 8
// grid and 4 parts in the inventory, the usual size from curriculum level 2 on). Smaller tasks keep
// that scale, with more air around them, so parts don't shrink from one task to the next; only
// larger ones zoom out (docs/gui.md §6).
const REFERENCE_BOARD = { grid: EDITOR.reference_grid, inventory: [] };
const REFERENCE_CAPACITY = EDITOR.reference_inventory;
const PICK_TOLERANCE_PX = 2; // shapes are hit-tested grown by this many screen pixels
const DRAG_THRESHOLD_PX = 4; // a press on the board that moves less than this is a click

// Props: `drag` is the current drag ({ item, rotation, base?, origin? }, see TutorScreen) or null;
// `onStartDrag(drag)` starts one, `onDrop(point)` ends it on a grid point, and `onPlan(fits)`
// reports whether the ghost fits (null off the grid). `selected` ({ kind, id } or null) is the
// selected board element, drawn with an outline; `onSelect(selection)` changes it.
// `highlights` are the tutor's ({ target: { component | wire | point }, style }), drawn as
// outlines in their style's color (docs/gui.md §4).
// `startBoard` is the task's starting board: the scene's bounds (and so its scale) are computed
// from it once per task and never change while the learner edits `board`. It also tells the
// task's own wires (not movable) from the ones the learner placed. While a placed
// element is being moved, `board` is the board without it.
export default function GridEditor({ board, startBoard, readings, drag, onStartDrag, onDrop, onPlan, selected, onSelect,
                                     highlights }) {
  const capacity = startBoard?.inventory?.length ?? 0;
  const host = useRef(null);
  const view = useRef(null);
  const pointer = useRef(null); // grid point under the dragged item's anchor (null off the grid)
  const pointerWorld = useRef(null); // world position of the dragged item's anchor, for the free-floating ghost
  const grab = useRef({ x: 0, y: 0 }); // pointer minus the item's anchor, fixed when the drag starts
  const pending = useRef(null); // a press on the board: a click (selection) or the start of a drag
  const [unsupported, setUnsupported] = useState(false);
  const [hover, setHover] = useState(null); // under the pointer: "grab" (movable), "select" (fixed) or null

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
    const reference = sceneBounds(REFERENCE_BOARD, layoutInventory(REFERENCE_BOARD, REFERENCE_CAPACITY));
    const state = { renderer, labels, scene, camera, root: null, inventory: null, layout: null, bounds: null,
                    gridBounds: null, inventoryOffset: 0,
                    reference: { width: reference.right - reference.left, height: reference.top - reference.bottom } };

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
      const r = state.reference;
      const scale = Math.max((Math.max(b.right - b.left, r.width) * MARGIN) / width,
                             (Math.max(b.top - b.bottom, r.height) * MARGIN) / height);
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
    for (const h of highlights ?? []) drawHighlight(state.root, h, selected);
    const node = selected && state.root.getObjectByName(selected.id);
    if (node && node.userData.kind === selected.kind) {
      // Blue for what the learner can change; grey for a fixed part or a task wire (docs/gui.md §4).
      outline(node, lift(board, selected, startBoard) ? STYLE.selection.color : STYLE.selection.locked_color);
    }
    state.scene.add(state.root);
    state.layout = layoutInventory(board, capacity);
    state.render();
  }, [board, startBoard, capacity, readings, selected, highlights, unsupported]);

  // Scene bounds: once per task, from its starting board. The inventory column reserves the
  // starting inventory's rows, so its width and height never change during the task.
  useEffect(() => {
    const state = view.current;
    if (!state || !startBoard) return;
    state.bounds = sceneBounds(startBoard, layoutInventory(startBoard, capacity));
    state.gridBounds = boardBounds(startBoard);
    state.fit();
  }, [startBoard, capacity, unsupported]);

  // The inventory region; rebuilt when its contents or the drag change.
  useEffect(() => {
    const state = view.current;
    if (!state || !state.layout) return;
    if (state.inventory) {
      state.scene.remove(state.inventory);
      disposeTree(state.inventory);
    }
    // A part being dragged leaves its slot at once; the slot closes up after the drop.
    const lifted = drag?.item.kind === "part" ? `part:${drag.item.id}` : null;
    state.inventory = inventoryNode(state.layout, lifted);
    state.inventory.position.x = state.inventoryOffset;
    state.scene.add(state.inventory);
    state.render();
  }, [board, drag, unsupported]);

  // World point under a pointer event.
  const worldAt = (event) => {
    const state = view.current;
    const rect = host.current?.getBoundingClientRect();
    if (!state || !rect) return null;
    const ndc = new THREE.Vector3(((event.clientX - rect.left) / rect.width) * 2 - 1,
                                  -((event.clientY - rect.top) / rect.height) * 2 + 1, 0);
    return ndc.unproject(state.camera);
  };
  // Where the dragged item's anchor is for a pointer event: the pointer minus the grab offset.
  const anchorAt = (event) => {
    const world = worldAt(event);
    return world && { x: world.x - grab.current.x, y: world.y - grab.current.y };
  };
  // Grid point nearest a world position, or null when it isn't over the grid.
  const snap = (world) => {
    if (!world || !board) return null;
    const point = [Math.round(world.x / CELL), Math.round(-world.y / CELL)];
    const { columns, rows } = board.grid;
    return point[0] >= 1 && point[1] >= 1 && point[0] <= columns && point[1] <= rows ? point : null;
  };
  // The element under a pointer event, hit-tested by its drawn shape: { world, hit } where
  // `hit` is the picked node's userData (inventory slot or board element) or null.
  const hitUnder = (event) => {
    const world = worldAt(event);
    const state = view.current;
    if (!world || !state || !board) return { world, hit: null };
    const tolerance = (PICK_TOLERANCE_PX * (state.camera.right - state.camera.left)) / host.current.clientWidth;
    return { world, hit: pickAt([state.inventory, state.root], world.x, world.y, tolerance) };
  };
  // What dragging `hit` would carry: { anchor (world), drag }, or null when it can't move.
  // Inventory items and movable board elements go through the same drag.
  const dragFor = (hit) => {
    const state = view.current;
    if (hit?.kind === "inventory") {
      const slot = state.layout.slots.find((s) => s.key === hit.key);
      if (!slot) return null;
      const anchor = slotAnchor(slot);
      return { anchor: { x: anchor.x + state.inventoryOffset, y: anchor.y },
               drag: { item: slot.item, rotation: slot.item.kind === "part" ? "E" : slot.item.rotation } };
    }
    const lifted = hit && lift(board, hit, startBoard);
    if (!lifted) return null;
    const anchor = toWorld(lifted.anchor);
    return { anchor: { x: anchor.x, y: anchor.y },
             drag: { item: lifted.item, rotation: lifted.rotation, base: lifted.base,
                     origin: { anchor: lifted.anchor, rotation: lifted.rotation } } };
  };
  // Start dragging, keeping the offset between the pointer (at `world`) and the item's anchor.
  const begin = (world, carried) => {
    setHover(null);
    grab.current = { x: world.x - carried.anchor.x, y: world.y - carried.anchor.y };
    pointerWorld.current = carried.anchor; // the ghost starts exactly where the item was
    pointer.current = carried.drag.base ? snap(carried.anchor) : null;
    onStartDrag?.(carried.drag);
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
    const held = pending.current;
    if (held) {
      if (Math.hypot(event.clientX - held.x, event.clientY - held.y) < DRAG_THRESHOLD_PX) return;
      held.moved = true; // no longer a click
      if (held.carried) {
        pending.current = null;
        begin(held.world, held.carried); // from where it was pressed: no jump
      }
      return;
    }
    if (!drag) {
      const { hit } = hitUnder(event);
      setHover(hit ? (dragFor(hit) ? "grab" : "select") : null);
      return;
    }
    pointerWorld.current = anchorAt(event);
    const point = snap(pointerWorld.current);
    const previous = pointer.current;
    const changed = point ? !previous || point[0] !== previous[0] || point[1] !== previous[1] : true;
    if (changed) {
      pointer.current = point; // null off the grid: the ghost floats, and a release there snaps back
      redraw((n) => n + 1);
    }
  };
  const press = (event) => {
    const { world, hit } = hitUnder(event);
    const carried = dragFor(hit);
    if (carried) {
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId); // keep the drag when leaving the canvas
    }
    if (hit?.kind === "inventory") begin(world, carried);
    else pending.current = { x: event.clientX, y: event.clientY, world, hit, carried, moved: false };
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
    const held = pending.current;
    pending.current = null;
    if (held && !held.moved) {
      // A click: select the element under it, or deselect on empty space.
      onSelect?.(held.hit ? { kind: held.hit.kind, id: held.hit.id } : null);
      return;
    }
    if (!drag) return;
    const point = snap(anchorAt(event));
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
      className={`grid-editor${drag ? " dragging" : ""}${hover === "grab" ? " over-item" : ""}${hover === "select" ? " over-fixed" : ""}`}
      aria-label="Grid"
      onPointerDown={press}
      onPointerMove={move}
      onPointerLeave={leave}
      onPointerUp={drop}
    />
  );
}
