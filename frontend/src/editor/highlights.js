// Tutor highlights (docs/contract.md §1, TutorMessage.meta.highlights): which ones still show.
// A highlight lasts until the next tutor message, or until the learner edits the highlighted element.

// The highlighted element in `board`, as JSON (null when it's gone); points have no element.
function elementOf(board, target) {
  const element = target.component
    ? board?.components.find((c) => c.id === target.component)
    : target.wire && board?.wires.find((w) => w.id === target.wire);
  return element ? JSON.stringify(element) : null;
}

// The highlights from a tutor message that arrived with board `then`, still live on board `now`:
// component and wire highlights drop once their element is moved, rotated or removed.
export function liveHighlights(highlights, then, now) {
  return (highlights ?? []).filter(({ target }) => target.point || elementOf(now, target) === elementOf(then, target));
}
