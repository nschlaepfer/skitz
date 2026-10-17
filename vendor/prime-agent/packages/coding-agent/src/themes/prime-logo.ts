/**
 * Pre-rendered ASCII versions of the Prime butterfly mark.
 *
 * Source: assets/brand/prime-butterfly.svg
 * Re-render at any width: `uv run scripts/render-logo.py --width N`
 */

import { IS_SKITZ } from "../product.js";
import { SKITZ_LOGO } from "./skitz-logo.js";

/** Keep the inherited export contract while choosing the active product's mark. */
export const PRIME_BUTTERFLY_LOGO = IS_SKITZ
	? SKITZ_LOGO
	: `                          ▄▄███▀
    ▄▄▄▄▄              ▄█████▀
    ██████▄         ▄██████▀
   ▄███▀███▄     ▄███▀▄██▀
   ███ ▄████▄▄▄████▀▄▄██
  ▀██  ▀█████████▀▀▀▀▀▀
  ▄██   ██████▀▀ ▄███
 █████    ▀█▄▄▄█████▀
███████▄  ████████▀
▀███▀▀    █████▀`;
