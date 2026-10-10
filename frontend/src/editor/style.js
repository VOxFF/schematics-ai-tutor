// Loads schematic-style.yaml: the editor's sizes and colors.
import { parse } from "yaml";
import raw from "./schematic-style.yaml?raw";

export const STYLE = parse(raw);

// Grid spacing in world units; the style's sizes are relative to it.
export const CELL = 40;
