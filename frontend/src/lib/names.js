// A friendly name for a learner who leaves the research name blank (docs/design.md §5).
const ADJECTIVES = ["Curious", "Bright", "Steady", "Clever", "Patient", "Bold", "Quiet", "Keen", "Lucky", "Swift"];
const ANIMALS = ["Otter", "Falcon", "Panda", "Fox", "Heron", "Lynx", "Badger", "Owl", "Dolphin", "Koala"];

const pick = (list) => list[Math.floor(Math.random() * list.length)];

export const randomName = () => `${pick(ADJECTIVES)} ${pick(ANIMALS)} ${10 + Math.floor(Math.random() * 90)}`;
