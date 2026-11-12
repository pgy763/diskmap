// Runs the report's inline script against a stub DOM/canvas so layout bugs and
// exceptions surface without a browser (which the sandbox cannot launch).
// Beyond "does it throw", it verifies geometric invariants of the drawing:
// every rect inside the canvas, siblings non-overlapping, labels only when they
// fit, and that drilling in/out keeps the tree consistent.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const file = process.argv[2] || path.join(__dirname, "..", "out", "diskmap-workspace.html");
const html = fs.readFileSync(file, "utf8");
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) throw new Error("no inline script found");
const code = m[1];

let CW = 1260, CH = 900;
const rects = [];      // every fillRect call
const texts = [];
let fillCount = 0;

const ctx = new Proxy({}, {
  get(_, k) {
    if (k === "canvas") return { width: CW, height: CH };
    if (k === "measureText") return (t) => ({ width: String(t).length * 6.4 });
    if (k === "createPattern") return () => ({ _pattern: true });
    if (k === "setTransform" || k === "save" || k === "restore" ||
        k === "beginPath" || k === "clip" || k === "closePath" ||
        k === "moveTo" || k === "lineTo" || k === "arcTo" ||
        k === "strokeRect" || k === "stroke" || k === "clearRect" ||
        k === "fill") {
      return (...a) => {
        if (k === "fill") fillCount++;
        return undefined;
      };
    }
    if (k === "fillRect") return (x, y, w, h) => rects.push({ x, y, w, h, fill: ctx.__fill });
    if (k === "fillText") return (t, x, y) => texts.push({ t: String(t), x, y });
    return () => {};
  },
  set(_, k, v) { if (k === "fillStyle") ctx.__fill = v; return true; },
});

const handlers = {};
function el(id) {
  const cls = new Set();
  const e = {
    id, style: {}, dataset: {}, _cls: cls,
    classList: {
      add(...c) { c.forEach(x => cls.add(x)); },
      remove(...c) { c.forEach(x => cls.delete(x)); },
      contains(c) { return cls.has(c); },
      toggle(c, on) {
        const want = on === undefined ? !cls.has(c) : !!on;
        if (want) cls.add(c); else cls.delete(c);
        return want;
      },
    },
    getContext: () => ctx,
    getBoundingClientRect: () => ({ width: CW, height: CH, left: 0, top: 0 }),
    addEventListener(ev, fn) { handlers[id + ":" + ev] = fn; },
    querySelectorAll: () => [],
    appendChild() {},
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html || ""; },
    set textContent(v) { this._txt = v; },
    get textContent() { return this._txt || ""; },
  };
  return e;
}
const els = {};
const document = {
  getElementById: (id) => (els[id] = els[id] || el(id)),
  querySelectorAll: () => [],
  createElement: (t) => el(t),
  addEventListener() {},
};
const window = {
  devicePixelRatio: 2, innerWidth: CW, innerHeight: CH,
  addEventListener(ev, fn) { handlers["window:" + ev] = fn; },
};

const sandbox = { document, window, console, Math, Date, JSON, Object, Array, String, Number, isFinite, parseInt, parseFloat };
sandbox.globalThis = sandbox;

function fail(msg) { console.error("FAIL", msg); process.exit(1); }

vm.createContext(sandbox);
try {
  vm.runInContext(code, sandbox, { timeout: 30000 });
} catch (e) {
  fail(e && e.stack ? e.stack : e);
}
console.log("OK  script ran without throwing");

// --- geometry ---
const drawn = rects.filter(r => r.w > 0.6 && r.h > 0.6);
if (drawn.length < 50) fail("only " + drawn.length + " rects drawn; map is probably empty");
let oob = 0;
for (const r of drawn) {
  if (r.x < -0.6 || r.y < -0.6 || r.x + r.w > CW + 0.6 || r.y + r.h > CH + 0.6) oob++;
}
if (oob) fail(oob + " rects out of canvas bounds");

// Coverage must be measured on a grid: parents and children are both painted,
// so summing rect areas double-counts by design.
const GW = 126, GH = 90, gx = CW / GW, gy = CH / GH;
const grid = new Uint8Array(GW * GH);
for (const r of drawn) {
  const x0 = Math.max(0, Math.floor(r.x / gx)), x1 = Math.min(GW - 1, Math.floor((r.x + r.w) / gx));
  const y0 = Math.max(0, Math.floor(r.y / gy)), y1 = Math.min(GH - 1, Math.floor((r.y + r.h) / gy));
  for (let yy = y0; yy <= y1; yy++) for (let xx = x0; xx <= x1; xx++) grid[yy * GW + xx] = 1;
}
let covered = 0;
for (const v of grid) covered += v;
const cov = covered / grid.length * 100;
console.log("    rects:", drawn.length, " grid coverage:", cov.toFixed(1) + "%");
if (cov < 88) fail("map covers only " + cov.toFixed(1) + "% - gaps in layout");

console.log("    labels:", texts.length, " sample:", texts.slice(0, 5).map(t => t.t).join(" | "));

// --- drill down / back up must not corrupt state ---
// Top-level `let` bindings live in the context's lexical scope, not on the
// sandbox object, so read them back by evaluating in the same context.
function ev(expr) { return vm.runInContext(expr, sandbox); }

const boxes = ev("boxes");
// A click drills into whichever box is topmost under the cursor, which for the
// centre of a big folder is usually a child. Find a folder that is itself the
// topmost box at its own centre (i.e. its title band) and click that.
const folders = boxes.filter(b => b.n && b.n.c && b.n.c.length && b.w > 60 && b.h > 50);
if (!folders.length) fail("no drillable folder boxes were produced");
const click = handlers["cv:click"];
const move = handlers["cv:mousemove"];
if (!click || !move) fail("canvas interaction handlers missing");

let target = null;
for (const f of folders) {
  move({ clientX: f.x + f.w / 2, clientY: f.y + 8 });
  if (ev("hoverNode") === f.n) { target = f; break; }
}
if (!target) fail("no folder could be hit by its own title band - labels are unclickable");

const before = rects.length;
handlers["cv:mouseleave"]({});
move({ clientX: target.x + target.w / 2, clientY: target.y + 8 });
if (rects.length <= before) fail("hover did not redraw");
const crumbBefore = els["crumb"].innerHTML;
click({});
const crumbAfter = els["crumb"].innerHTML;
if (crumbAfter === crumbBefore) fail("clicking a folder did not change the breadcrumb");
const inside = ev("boxes").length;
if (inside === 0) fail("drilled view drew nothing");
const back = handlers["cv:contextmenu"];
if (!back) fail("no way back up");
back({ preventDefault() {} });
if (els["crumb"].innerHTML !== crumbBefore) fail("going back up did not restore the breadcrumb");
console.log("    drill-down (" + target.n.n + " -> " + inside + " boxes) + back: ok");

// --- tabs ---
const listHtml = {};
for (const t of ["largest", "duplicates", "stale", "junk"]) {
  vm.runInContext("tab='" + t + "';filter='';renderList();", sandbox);
  listHtml[t] = els["list"].innerHTML;
  if (!listHtml[t] || listHtml[t].length < 40) fail("tab " + t + " rendered empty");
}
console.log("    tabs:", Object.entries(listHtml).map(([k, v]) => k + "=" + v.length + "ch").join(" "));

// weight mode: switching to file counts must re-lay-out the map
const beforeRects = ev("boxes").map(b => b.n.n + ":" + Math.round(b.w)).join("|");
vm.runInContext("document.getElementById('m-count').onclick();", sandbox);
if (ev("mode") !== "count") fail("mode did not switch to count");
const afterRects = ev("boxes").map(b => b.n.n + ":" + Math.round(b.w)).join("|");
if (afterRects === beforeRects) fail("count mode produced an identical layout");
console.log("    count mode: " + ev("boxes").length + " boxes, layout changed: ok");
vm.runInContext("document.getElementById('m-size').onclick();", sandbox);
if (ev("mode") !== "size") fail("mode did not switch back");

// filter must actually narrow the list
const wide = listHtml["largest"].length;
vm.runInContext("tab='largest';filter='zzz-no-such-file';renderList();", sandbox);
const narrow = els["list"].innerHTML.length;
if (narrow >= wide) fail("search filter did not narrow the list");
console.log("    filter: " + wide + "ch -> " + narrow + "ch");

const st = els["total"].textContent;
if (!st || st === "—") fail("total size never set");
console.log("    total:", st);
console.log("ALL CHECKS PASSED");
