#!/usr/bin/env node
// node hooks/selftest.js
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { check, lastTurn } = require('./check.js');
const { ruleTargetFor, fileOpReason } = require('./inject.js');

const hit = (text, user) => check(text, user).length > 0;

// The shared corpus. tools/lint.py runs the same rows, so a divergence between
// the two implementations fails here instead of rotting silently.
{
  const corpus = JSON.parse(
    fs.readFileSync(path.join(__dirname, '..', 'tests', 'corpus.json'), 'utf8')
  );
  let ran = 0;
  for (const c of corpus.cases) {
    if (!c.tools.includes('hook')) continue;
    ran++;
    assert.strictEqual(
      hit(c.text),
      c.hit,
      `corpus: expected hit=${c.hit} (${c.why}) for ${JSON.stringify(c.text)}`
    );
  }
  console.log(`corpus ok (${ran} cases)`);
}

// The blocking sets fire.
assert.ok(hit('We leverage the cache.'), 'banned word missed');
assert.ok(hit("It's not a cache, it's a buffer."), 'contrast construction missed');
assert.ok(hit('This is load-bearing for the retry path.'), 'phrase missed');
assert.ok(hit('Three things matter here.'), 'counting missed');
assert.ok(hit('To be clear, the lock is held.'), 'meta-commentary missed');
assert.ok(
  hit('- **One** a\n- **Two** b\n- **Three** c'),
  'bold-every-bullet missed'
);
// One hand-edited plain bullet does not rescue the list.
assert.ok(
  hit('- **One** a\n- **Two** b\n- **Three** c\n- **Four** d\n- five e'),
  'bold-bullet ratio missed'
);
assert.ok(!hit('- one a\n- **Two** b\n- three c'), 'bold-bullet false positive');

assert.ok(hit("Say the word and I'll add the counter."), 'servile closer missed');
assert.ok(hit('Just let me know.'), 'servile closer missed');
assert.ok(hit('Happy to walk through the retry path.'), 'servile closer missed');
assert.ok(hit('Hope this helps.'), 'servile closer missed');
// A plain question is allowed.
assert.ok(!hit('Postgres or SQLite?'), 'plain question blocked');

assert.ok(hit("Point me at the failing case and I'll fix it."), 'staged trigger missed');
assert.ok(hit("Once you confirm the scope, I'll rewrite status.md."), 'staged trigger missed');
assert.ok(hit("Give me the go-ahead and the migration runs tonight."), 'staged trigger missed');
// The offer forms the trigger rule points at.
assert.ok(!hit('Would you like me to add metrics?'), 'offer as a question blocked');
assert.ok(!hit('I can add metrics if you want.'), 'offer as a capability blocked');

// Reflexive agreement. Needs both sides of the turn, so the hook alone runs it.
{
  const cap = (a, u) => check(a, u).some(v => /cited nothing/.test(v.match));
  const pushback = 'no, thats wrong, the mutex is needed';
  assert.ok(cap('You are right. I will fix it.', pushback), 'capitulation missed');
  assert.ok(cap('Yes. Done.', 'actually the timeout is 30s not 10s'), 'capitulation missed');
  // Evidence rescues the agreement. Checking the claim is the whole point.
  assert.ok(
    !cap('You are right. The write happens at `worker.go:88`.', pushback),
    'agreement with evidence blocked'
  );
  // A disagreement is what the rule wants to see.
  assert.ok(
    !cap('The mutex adds nothing. Only the reader thread touches it.', pushback),
    'disagreement blocked'
  );
  // No pushback means no capitulation, whatever the reply says.
  assert.ok(
    !cap('You are right. I will fix it.', 'can you add a retry to the fetch'),
    'fired without a pushback'
  );
}

// A soft finding reports and never blocks, so a corrective list survives.
{
  const soft = check('Use tabs, not spaces, in this file.');
  assert.ok(soft.length, 'corrective list not noted');
  assert.ok(soft.every(v => v.soft), 'corrective list must stay soft');
  const hard = check('Settings are enforced, not a suggestion.');
  assert.ok(hard.some(v => !v.soft), 'appositive contrast must block');
}

assert.ok(hit('Yes, I read it. The lock is held.'), 'narration missed');
assert.ok(hit("Here's the actual shape of the deploy."), 'preamble missed');
assert.ok(hit('One thing I found while reading matters more.'), 'buried finding missed');
assert.ok(!hit('The runner polls /health until the version matches.'), 'plain report blocked');

// The length finding is soft: it reports and never blocks.
{
  const long = check('word '.repeat(500));
  const lengthFinding = long.find(v => /words of prose/.test(v.match));
  assert.ok(lengthFinding, 'length finding missed');
  assert.strictEqual(lengthFinding.soft, true, 'length finding must be soft');
  assert.ok(!check('The registry holds one lock.').some(v => v.soft), 'short reply flagged');
}

assert.ok(!hit('The harness runs the hook.'), 'ambiguous word blocked');
assert.ok(!hit('A robust retry covers the landscape.'), 'ambiguous words blocked');

// Code and quotes are not prose.
assert.ok(!hit('Use `leverage` as the example word.'), 'inline code not skipped');
assert.ok(!hit('```\nWe leverage it.\n```'), 'fence not skipped');
assert.ok(!hit('> we leverage the cache'), 'blockquote not skipped');
assert.ok(
  !hit('If you ask "should we leverage the cache?", the reply may repeat it.'),
  'double-quoted citation not skipped'
);
// A quote must close on its own line to count as a citation.
assert.ok(hit('He said "we leverage\nthe cache" yesterday.'), 'multiline quote skipped');

// A word the user used is not the assistant's slop.
assert.ok(
  !hit('We leverage it there.', 'should we leverage the cache?'),
  'user-supplied word still blocked'
);

// Clean prose passes.
assert.ok(!hit('The registry holds one lock per vm. Stop() only signals.'), 'false positive');

// Findings carry the offending sentence, not just the word.
const found = check('The lock is fine. We leverage the cache heavily.');
assert.strictEqual(found.length, 1);
assert.match(found[0].sentence, /leverage the cache/);
assert.ok(!found[0].sentence.includes('lock is fine'), 'sentence split failed');

// lastTurn reads the whole turn, not just its closing message.
{
  const entry = (type, text, extra = {}) =>
    JSON.stringify({ type, uuid: `u-${text.slice(0, 6)}`, message: { content: [{ type: 'text', text }] }, ...extra });
  const toolUse = JSON.stringify({
    type: 'assistant',
    uuid: 'u-tool',
    message: { content: [{ type: 'tool_use', id: 't1', name: 'Read', input: {} }] },
  });
  const toolResult = JSON.stringify({
    type: 'user',
    uuid: 'u-res',
    toolUseResult: 'ok',
    message: { content: [{ type: 'tool_result', tool_use_id: 't1', content: 'we leverage nothing' }] },
  });

  const file = path.join(os.tmpdir(), 'anti-slop-selftest.jsonl');
  fs.writeFileSync(
    file,
    [
      entry('user', 'an older prompt'),
      entry('assistant', 'an older reply'),
      entry('user', 'the real prompt'),
      entry('assistant', 'We leverage the cache first.'),
      toolUse,
      toolResult,
      entry('assistant', 'The registry holds one lock.'),
    ].join('\n')
  );

  const turn = lastTurn(file);
  fs.unlinkSync(file);
  assert.match(turn.assistant, /leverage the cache/, 'mid-turn text dropped');
  assert.match(turn.assistant, /registry holds one lock/, 'final text dropped');
  assert.ok(!/older reply/.test(turn.assistant), 'previous turn leaked in');
  assert.strictEqual(turn.user, 'the real prompt');
  assert.strictEqual(turn.uuid, 'u-The re', 'uuid must be the final assistant message');
  assert.strictEqual(check(turn.assistant, turn.user).length, 1, 'mid-turn slop missed');
}

// The PostToolUse path speaks once per finding per turn. A repeat at every tool
// call is what makes an injected reminder get ignored.
{
  const { execFileSync } = require('child_process');
  const file = path.join(os.tmpdir(), 'anti-slop-selftest-mid.jsonl');
  const session = 'selftest-mid';
  const state = path.join(os.tmpdir(), `anti-slop-${session}.json`);
  const line = (type, text) =>
    JSON.stringify({ type, uuid: `u-${text.slice(0, 6)}`, message: { content: [{ type: 'text', text }] } });
  fs.writeFileSync(
    file,
    [line('user', 'fix the parser'), line('assistant', 'We leverage the cache first.')].join('\n')
  );
  const run = event =>
    execFileSync(process.execPath, [path.join(__dirname, 'inject.js')], {
      input: JSON.stringify({ hook_event_name: event, session_id: session, transcript_path: file }),
      encoding: 'utf8',
    });

  try {
    const first = JSON.parse(run('PostToolUse'));
    assert.strictEqual(first.hookSpecificOutput.hookEventName, 'PostToolUse');
    assert.match(first.hookSpecificOutput.additionalContext, /leverage/, 'mid-turn finding missed');
    assert.match(first.hookSpecificOutput.additionalContext, /possible editorial issues/i, 'style matches must be advisory');
    assert.ok(!/breaks the rules|hard rules|VIOLATED/.test(first.hookSpecificOutput.additionalContext), 'style matches must not be presented as violations');
    assert.strictEqual(run('PostToolUse'), '', 'mid-turn finding repeated');
    // The same finding must not arrive twice through two different hooks.
    assert.ok(!/leverage/.test(run('UserPromptSubmit')), 'finding reported twice');
  } finally {
    fs.unlinkSync(file);
    try { fs.unlinkSync(state); } catch { /* never written */ }
  }
}

// ruleTargetFor maps a tool call to one rule file. Unit-tested directly, so a
// new extension is one assertion away.
{
  const t = (tool, input) => ruleTargetFor({ tool_name: tool, tool_input: input });

  for (const f of ['a.py', 'b.js', 'c.ts', 'd.tsx', 'e.go', 'f.rs', 'g.rb', 'h.sh', 'i.sql', 'j.c', 'k.cpp', 'l.ipynb']) {
    const target = f.endsWith('.ipynb') ? t('NotebookEdit', { notebook_path: `/x/${f}` }) : t('Edit', { file_path: `/x/${f}` });
    assert.strictEqual(target, 'code', `${f} should route code`);
  }
  for (const f of ['R.md', 'n.mdx', 'd.rst', 'p.txt', 'a.adoc']) {
    assert.strictEqual(t('Write', { file_path: `/x/${f}` }), 'prose', `${f} should route prose`);
  }
  assert.strictEqual(t('MultiEdit', { file_path: '/x/m.go' }), 'code', 'MultiEdit on source routes code');

  for (const cmd of ['git commit -m "x"', 'cd repo && git commit --amend', 'git -c user.name=x commit -m y']) {
    assert.strictEqual(t('Bash', { command: cmd }), 'commit', `"${cmd}" should route commit`);
  }
  assert.strictEqual(t('Write', { file_path: '/r/.git/COMMIT_EDITMSG' }), 'commit', 'a commit message file routes commit');

  for (const [tool, input] of [
    ['Bash', { command: 'git status' }],
    ['Bash', { command: 'git log --oneline' }],
    ['Read', { file_path: '/x/a.py' }],
    ['Edit', { file_path: '/x/data.json' }],
    ['Edit', { file_path: '/x/config.yaml' }],
    ['Edit', { file_path: '/x/logo.png' }],
    ['Edit', { file_path: '/x/Makefile' }],
  ]) {
    assert.strictEqual(t(tool, input), null, `${tool} ${JSON.stringify(input)} should route nothing`);
  }
}

// The deterministic router injects one rule file per target, once per session.
{
  const { execFileSync } = require('child_process');
  const session = 'selftest-router';
  const state = path.join(os.tmpdir(), `anti-slop-${session}.json`);
  try { fs.unlinkSync(state); } catch { /* never written */ }
  const run = (tool, input) =>
    execFileSync(process.execPath, [path.join(__dirname, 'inject.js')], {
      input: JSON.stringify({
        hook_event_name: 'PostToolUse',
        session_id: session,
        transcript_path: '/nonexistent',
        tool_name: tool,
        tool_input: input,
      }),
      encoding: 'utf8',
    });

  try {
    assert.match(run('Edit', { file_path: '/tmp/x.py' }), /ANTI-SLOP CODE DIRECTIVE/, 'code rules not routed for a .py edit');
    assert.strictEqual(run('Edit', { file_path: '/tmp/y.py' }), '', 'code rules routed twice in one session');
    assert.match(run('Write', { file_path: '/tmp/README.md' }), /ANTI-SLOP PROSE DIRECTIVE/, 'prose rules not routed for a .md edit');
    assert.match(run('Bash', { command: 'git commit -m "fix"' }), /ANTI-SLOP COMMIT DIRECTIVE/, 'commit rules not routed for git commit');
    assert.strictEqual(run('Read', { file_path: '/tmp/x.py' }), '', 'a read must route nothing');
    assert.strictEqual(run('Bash', { command: 'git status' }), '', 'a non-commit git call must route nothing');
  } finally {
    try { fs.unlinkSync(state); } catch { /* never written */ }
  }
}

// The Bash guard flags file ops that belong to Write/Edit/Read, and passes the rest.
{
  const r = fileOpReason;
  assert.ok(r('sed -i s/a/b/ notes.txt'), 'sed -i not flagged');
  assert.ok(r('perl -pi -e s/a/b/ app.py'), 'perl -i not flagged');
  assert.ok(r('echo "x" > config.py'), 'redirect to source not flagged');
  assert.ok(r('cat <<EOF > server.js\nx\nEOF'), 'heredoc redirect not flagged');
  assert.ok(r('printf "%s" done >> README.md'), 'append to docs not flagged');
  assert.ok(r('tee out.md'), 'tee to a file not flagged');
  assert.ok(r('cat README.md'), 'cat of a doc not flagged');
  assert.ok(r('head -n 5 main.go'), 'head of source not flagged');

  assert.strictEqual(r('npm test'), null, 'plain command flagged');
  assert.strictEqual(r('echo hi > /dev/null'), null, 'a no-extension redirect flagged');
  assert.strictEqual(r('cat foo.log'), null, 'a log read flagged');
  assert.strictEqual(r('grep foo bar.py'), null, 'grep flagged');
  assert.strictEqual(r('git commit -m "fix"'), null, 'commit flagged');
  assert.strictEqual(r('rm -rf build'), null, 'rm flagged');
}

// The guard posture comes from ANTI_SLOP_TOOL_GUARD: ask by default, deny, or off.
{
  const { execFileSync } = require('child_process');
  const run = (command, env) =>
    execFileSync(process.execPath, [path.join(__dirname, 'inject.js')], {
      input: JSON.stringify({ hook_event_name: 'PreToolUse', tool_name: 'Bash', tool_input: { command } }),
      encoding: 'utf8',
      env: { ...process.env, ...env },
    });

  const ask = JSON.parse(run('echo x > app.py', { ANTI_SLOP_TOOL_GUARD: 'ask' }));
  assert.strictEqual(ask.hookSpecificOutput.permissionDecision, 'ask', 'default posture must ask');
  assert.match(ask.hookSpecificOutput.permissionDecisionReason, /Write or Edit/, 'reason must name the tool');

  const deny = JSON.parse(run('sed -i s/a/b/ app.py', { ANTI_SLOP_TOOL_GUARD: 'deny' }));
  assert.strictEqual(deny.hookSpecificOutput.permissionDecision, 'deny', 'deny posture must deny');

  assert.strictEqual(run('echo x > app.py', { ANTI_SLOP_TOOL_GUARD: 'off' }), '', 'off posture must stay silent');
  assert.strictEqual(run('npm test', { ANTI_SLOP_TOOL_GUARD: 'deny' }), '', 'a plain command must pass');
}

// The auto permission mode turns the guard off and drops the tool-choice rule.
{
  const { execFileSync } = require('child_process');
  const run = payload =>
    execFileSync(process.execPath, [path.join(__dirname, 'inject.js')], {
      input: JSON.stringify(payload),
      encoding: 'utf8',
    });
  const guard = mode =>
    run({ hook_event_name: 'PreToolUse', permission_mode: mode, tool_name: 'Bash', tool_input: { command: 'sed -i s/a/b/ app.py' } });

  assert.strictEqual(guard('auto'), '', 'the guard must stay silent in auto mode');
  assert.ok(guard('acceptEdits'), 'the guard must still fire in acceptEdits mode');
  assert.ok(guard(undefined), 'the guard must still fire when the mode is absent');

  const rules = mode => run({ hook_event_name: 'SessionStart', permission_mode: mode });
  assert.ok(!/Reach for the dedicated tool/.test(rules('auto')), 'auto mode must not carry the tool-choice rule');
  assert.match(rules('default'), /Reach for the dedicated tool/, 'every other mode keeps the tool-choice rule');
  assert.ok(!/not-in-auto/.test(rules('default')), 'the marker must not reach the model');
}

console.log('selftest ok');
