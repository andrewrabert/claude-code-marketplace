# jev-scan states

With `--base`, `jev-scan.py` sends jev one request per state, and each state is a unified diff. Every question set judges the `+` lines of a state and reads the other lines as context.

- `-e`/`--evaluate` sets what each state holds: `hunk` (default), `file` or `diff`.
- `-C`/`--context` sets the lines of context on each side of a hunk: a count (default 20), or `full` for every line of the file.
- `-a`/`--all-added` marks every line `+`.

`--dry-run` prints each state instead of sending it, and `-v`/`--verbose` prints each request it sends to stderr.

## The change

Every example below is `jev-scan.py --base HEAD --dry-run` over this change to `a.rs` and `b.rs`, with `-C 1` unless it says otherwise:

```diff
@@ -1,6 +1,6 @@
 fn one() -> u32 {
     let x = 1;
-    let y = 2;
+    let y = 5;
     x + y
 }
@@ -15,7 +15,7 @@ fn unchanged() -> u32 {
 fn two() -> u32 {
     let a = 10;
-    let b = 20;
+    let b = 25;
     a + b
 }
```

```diff
@@ -1,3 +1,3 @@
 fn four() -> u32 {
-    4
+    40
 }
```

`a.rs` also holds `unchanged()` between them and `three()` after them. A state holds the added and context lines of the change. In a state, each file opens with `diff --git`, `---` and `+++` lines; the examples start after those lines, and `-e diff` keeps the `diff --git` lines to show where each file starts.

## `-e hunk`

One state per hunk, with the file header and the hunk's lines; a state holds no `@@` hunk header. This change gives 3 states; the first is:

```diff
     let x = 1;
+    let y = 5;
     x + y
```

## `-e file`

One state per file, holding all of its hunks. This change gives 2 states; the one for `a.rs` is:

```diff
@@ -2,3 +2,3 @@ fn one() -> u32 {
     let x = 1;
+    let y = 5;
     x + y
@@ -17,3 +17,3 @@ fn two() -> u32 {
     let a = 10;
+    let b = 25;
     a + b
```

## `-e diff`

One state holding every file's diff:

```diff
diff --git a/a.rs b/a.rs
@@ -2,3 +2,3 @@ fn one() -> u32 {
     let x = 1;
+    let y = 5;
     x + y
@@ -17,3 +17,3 @@ fn two() -> u32 {
     let a = 10;
+    let b = 25;
     a + b
diff --git a/b.rs b/b.rs
@@ -1,3 +1,3 @@
 fn four() -> u32 {
+    40
 }
```

## `-C`

git merges hunks whose context meets, so more context gives fewer, larger hunks. With `-C full`, each file's diff is one hunk holding the whole file, so `-e hunk` and `-e file` give the same states. The state for `a.rs` is:

```diff
@@ -1,24 +1,24 @@
 fn one() -> u32 {
     let x = 1;
+    let y = 5;
     x + y
 }

 fn unchanged() -> u32 {
     let p = 1;
     let q = 2;
     let r = 3;
     let s = 4;
     let t = 5;
     p + q + r + s + t
 }

 fn two() -> u32 {
     let a = 10;
+    let b = 25;
     a + b
 }

 fn three() -> u32 {
     3
 }
```

The default `-C 20` also gives this state, since `a.rs` is 24 lines.

## `-a`

Marks every context line `+`, so jev judges the unchanged lines too. The first `-e hunk -a` state is:

```diff
+    let x = 1;
+    let y = 5;
+    x + y
```

`-C full -a` judges every line of each changed file.

## Repeated `-e`

Each `-e` adds its own states, and each finding's `evaluated` field names the value that produced it. `-e hunk -e file` gives the 3 `hunk` states and the 2 `file` states above, 5 in all.

## Untracked files

An untracked file is all added, so it is one state of `+` lines under `-e file` and `-e diff`, whatever `-C` is:

```diff
@@ -0,0 +1,3 @@
+fn five() -> u32 {
+    5
+}
```

Under `-e hunk`, each top-level item of the file is its own state, also without the `@@` line.
