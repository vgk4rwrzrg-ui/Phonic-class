"""
Regression tests for repeated graphemes in a word (BULL, EGG, MOON, SHEEP).

Bug found in testing: with two identical letters, only one specific tile copy
was accepted per box, so dropping the "other" L of BULL into the third box was
scored as a miss ("So close!") even though the letter was right.  Matching is
now done on the grapheme, so either copy may go in first.

Run with: python manage.py test game.tests_duplicate_graphemes
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from django.test import TestCase

GAME_HTML = os.path.join("game", "templates", "game", "game.html")


def _read_game_html():
    with open(GAME_HTML, encoding="utf-8") as fh:
        return fh.read()


def _extract_function(source, name):
    """Pull one top-level `function name(...) { ... }` out of the template JS."""
    start = source.index("function %s(" % name)
    depth, i = 0, source.index("{", start)
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1


class DuplicateGraphemeTemplateTests(TestCase):
    """Pin the grapheme-based matching so a refactor cannot bring the bug back."""

    def test_slots_expose_the_grapheme_they_need(self):
        html = _read_game_html()
        self.assertIn("var roundUnits = []", html)
        self.assertIn("roundUnits = units.map(function (u) { return u.g; });", html)

    def test_drag_game_matches_grapheme_not_tile_identity(self):
        html = _read_game_html()
        self.assertIn("var needed = roundUnits[slot];", html)
        self.assertIn("tile.letter === needed", html)
        # The old identity check rejected the second copy of a repeated letter.
        self.assertNotIn("if (slot === tile.slot && !hit.classList.contains('filled'))", html)

    def test_boss_fight_matches_grapheme_not_tile_identity(self):
        html = _read_game_html()
        self.assertNotIn("o.g === expected.g && o.i === bossState.boxIdx", html)
        self.assertIn("if (!o.decoy && expected && o.g === expected.g) {", html)

    def test_decoys_are_still_rejected_in_both_modes(self):
        html = _read_game_html()
        self.assertIn("!tile.decoy", html)   # drag game
        self.assertIn("!o.decoy", html)      # boss fight

    def test_balloon_round_already_matches_by_value(self):
        # Balloons were never identity-matched; keep it that way.
        html = _read_game_html()
        self.assertIn("if (b.g === expected) {", html)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class DuplicateGraphemeBehaviourTests(TestCase):
    """Run the real handleDrop/wordToUnits code from game.html under node."""

    def _run(self, word, tray_index, target_slot):
        html = _read_game_html()
        js = "\n".join([
            "var LETTER_SOUNDS = " + json.dumps({c: c for c in "abcdefghijklmnopqrstuvwxyz"}) + ";",
            "var DIGRAPH_SOUNDS = {sh:'shh', ch:'chuh', th:'thuh', ck:'kuh', ee:'ee', oo:'oo'};",
            "var TRIGRAPH_SOUNDS = {igh:'eye', tch:'chuh'};",
            _extract_function(html, "wordToUnits"),
            _extract_function(html, "handleDrop"),
            """
var missed = false, hinted = false;
function vibrate() {}
function playUnit() {}
function api() { missed = true; return { then: function () {} }; }
function snapBack() {}
function showHint() { hinted = true; }
function checkWin() {}
var WORD = process.argv[2];
var units = wordToUnits(WORD);
var roundUnits = units.map(function (u) { return u.g; });
var tiles = units.map(function (u, i) { return { letter: u.g, sound: u.sound, slot: i, placed: false }; });
tiles.push({ letter: 'Z', sound: 'z', slot: -1, placed: false, decoy: true });
var boxes = roundUnits.map(function (g, i) {
  return {
    dataset: { slot: String(i) },
    filled: false,
    classList: {
      contains: function (c) { return c === 'filled' && boxes[i].filled; },
      add: function (c) { if (c === 'filled') boxes[i].filled = true; }
    },
    getBoundingClientRect: function () { return { left: i * 100, right: i * 100 + 90, top: 0, bottom: 90 }; }
  };
});
global.document = { querySelectorAll: function () { return boxes; } };
var tile = tiles[parseInt(process.argv[3], 10)];
var slot = parseInt(process.argv[4], 10);
var el = { style: {}, classList: { add: function () {}, remove: function () {} }, addEventListener: function () {} };
handleDrop(el, tile, slot * 100 + 45, 45);
console.log(JSON.stringify({ placed: !!tile.placed, filled: boxes[slot].filled, missed: missed, hinted: hinted }));
""",
        ])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "harness.js")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(js)
            out = subprocess.run(
                ["node", path, word, str(tray_index), str(target_slot)],
                capture_output=True, text=True, timeout=30, check=True,
            )
        return json.loads(out.stdout.strip().splitlines()[-1])

    def test_second_l_of_bull_accepted_in_the_third_box(self):
        """The reported edge case: tiles[3] is the 4th-box L, dropped in box 3."""
        res = self._run("bull", 3, 2)
        self.assertTrue(res["placed"])
        self.assertTrue(res["filled"])
        self.assertFalse(res["missed"], "a correct letter must not be reported as a trouble sound")
        self.assertFalse(res["hinted"], "a correct letter must not show the 'So close!' hint")

    def test_first_l_of_bull_still_accepted_in_the_third_box(self):
        res = self._run("bull", 2, 2)
        self.assertTrue(res["placed"])
        self.assertFalse(res["hinted"])

    def test_either_l_of_bull_accepted_in_the_fourth_box(self):
        for tray_index in (2, 3):
            res = self._run("bull", tray_index, 3)
            self.assertTrue(res["placed"], "tile %d rejected in box 4" % tray_index)
            self.assertFalse(res["hinted"])

    def test_repeated_letters_in_other_words(self):
        self.assertTrue(self._run("egg", 2, 1)["placed"])       # 2nd G into 1st G box
        self.assertTrue(self._run("toffee", 3, 2)["placed"])    # 2nd F into 1st F box
        self.assertTrue(self._run("little", 4, 0)["placed"])    # far-apart repeated L

    def test_wrong_letter_is_still_a_miss(self):
        res = self._run("bull", 0, 2)   # B dropped where an L belongs
        self.assertFalse(res["placed"])
        self.assertTrue(res["missed"])
        self.assertTrue(res["hinted"])

    def test_decoy_tile_is_still_a_miss(self):
        res = self._run("bull", 4, 2)   # the Z decoy
        self.assertFalse(res["placed"])
        self.assertTrue(res["hinted"])
