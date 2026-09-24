#!/usr/bin/env node
// SessionStart, SubagentStart, PostToolUse and UserPromptSubmit hook. All four
// reach the model. Any other event exits silently.
//
// SessionStart fires on startup, resume, clear, and compact. The compact matcher
// is what restores the rules after a summarization drops them.
//
// PostToolUse reports a finding mid-turn, next to the tool result.
//
// UserPromptSubmit does two jobs. It lints the previous assistant turn, which is
// on disk by now, and it restates a one-line reminder every REMIND_EVERY
// prompts, because a rule stated once at turn 1 stops steering by turn 40.

const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { check, lastTurn } = require('./check.js');

const REMIND_EVERY = Number(process.env.ANTI_SLOP_REMIND_EVERY || 9);
const MAX_REPORTED = 8;
const RULES_DIR = path.join(__dirname, 'rules');
const CODE_EXT = new Set([
  '.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.kt', '.c',
  '.h', '.cc', '.cpp', '.cs', '.php', '.swift', '.scala', '.rb', '.sh',
  '.bash', '.zsh', '.sql', '.lua', '.hs', '.ipynb',
]);
const PROSE_EXT = new Set(['.md', '.mdx', '.rst', '.txt', '.adoc']);
// Extensions the Bash guard treats as a real file: a redirect or a cat onto one
// of these is a Write/Edit/Read job. A target with no known extension (a temp
// file, /dev/null, a pipe) passes.
const GUARD_EXT = [...CODE_EXT, ...PROSE_EXT].map(e => e.slice(1)).join('|');
const NOT_IN_AUTO = '<!-- curt: not-in-auto -->';
const ONLY_IN_AUTO = '<!-- curt: only-in-auto -->';
const DIRECTIVE = {
  sycophancy: 'Response substance',
  word: 'Word choice',
  phrase: 'Construction',
  structure: 'Passage structure',
  verbosity: 'Length',
  ambiguous: 'Context-dependent wording',
  default: 'Editorial note',
};
const SHORT =
  'CURT WRITING REMINDER: preserve meaning, qualifications, and the author\'s ' +
  'voice. Make the smallest useful edit. Remove empty rhetoric without ' +
  'inventing facts or experience. Judge lint matches in context; they are ' +
  'suggestions, not mandatory rewrites or proof of AI authorship.';

// readRuleFile strips the ignore marker so the injected context omits it.
// A line tagged NOT_IN_AUTO drops out under the auto permission mode.
// A line tagged ONLY_IN_AUTO drops out unless the mode is auto.
function readRuleFile(name, mode) {
  try {
    return fs
      .readFileSync(path.join(RULES_DIR, `${name}.md`), 'utf8')
      .split('\n')
      .filter(line => mode !== 'auto' || !line.includes(NOT_IN_AUTO))
      .filter(line => mode === 'auto' || !line.includes(ONLY_IN_AUTO))
      .join('\n')
      .replaceAll(NOT_IN_AUTO, '')
      .replaceAll(ONLY_IN_AUTO, '')
      .replace(/^<!-- anti-slop:.*$/gm, '')
      .trim();
  } catch {
    return null;
  }
}

// Deterministic router. The tool that just ran picks one rule file: a source
// edit gets code, a docs edit gets prose, a git commit gets commit. The choice
// is a pure function of the tool name, the command, and the file extension.
// Anything else routes nothing.
function ruleTargetFor(data) {
  const input = data.tool_input || {};
  // git writes the message inline (-m) or through an editor on COMMIT_EDITMSG.
  // A -F/-C flag reads a file the model wrote with an earlier Write call.
  if (data.tool_name === 'Bash' && /\bgit\b[^\n]*\bcommit\b/.test(input.command || '')) {
    return 'commit';
  }
  if (['Write', 'Edit', 'MultiEdit', 'NotebookEdit'].includes(data.tool_name)) {
    const file = input.file_path || input.notebook_path || '';
    const base = path.basename(file);
    if (base === 'COMMIT_EDITMSG' || base === 'MERGE_MSG' || base === 'TAG_EDITMSG') {
      return 'commit';
    }
    const ext = path.extname(file).toLowerCase();
    if (PROSE_EXT.has(ext)) return 'prose';
    if (CODE_EXT.has(ext)) return 'code';
  }
  return null;
}

// A Bash command that reads or writes a real file is doing a Write/Edit/Read
// tool's job. Detection stays narrow: an in-place editor always counts, and a
// redirect, a tee, or a cat counts only when the target ends in a known
// extension. A temp file, /dev/null, or a pipe carries no extension and passes.
function fileOpReason(command) {
  const cmd = command || '';
  const file = `[^\\s|&;<>()"']*\\.(?:${GUARD_EXT})\\b`;
  if (/\bsed\b[^|&;]*\s-[a-z]*i\b/.test(cmd) || /\bperl\b[^|&;]*\s-[a-z]*i\b/.test(cmd)) {
    return 'use the Edit tool for an in-place change instead of sed -i.';
  }
  if (new RegExp(`>>?\\s*${file}`).test(cmd)) {
    return 'use the Write or Edit tool to change a file instead of a shell redirect.';
  }
  if (new RegExp(`\\btee\\b[^|&;]*\\s${file}`).test(cmd)) {
    return 'use the Write tool to create a file instead of tee.';
  }
  if (new RegExp(`\\b(?:cat|head|tail)\\b[^|&;]*\\s${file}`).test(cmd)) {
    return 'use the Read tool to read a file instead of cat, head, or tail.';
  }
  return null;
}

// PreToolUse guard on Bash. The reason reaches the model, so it retries with the
// native tool. Posture comes from ANTI_SLOP_TOOL_GUARD: "ask" (default) routes
// to the user's permission prompt, "deny" blocks outright, "off" disables it.
//
// The auto permission mode tells the model to read and edit through Bash. The
// guard stays off there. It would contradict the harness and spend a permission
// decision on every cat.
function toolGuard(data) {
  const posture = (process.env.ANTI_SLOP_TOOL_GUARD || 'ask').toLowerCase();
  if (posture === 'off' || data.permission_mode === 'auto') return;
  if (data.tool_name !== 'Bash') return;
  const reason = fileOpReason((data.tool_input || {}).command);
  if (!reason) return;
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: posture === 'deny' ? 'deny' : 'ask',
        permissionDecisionReason: `anti-slop: ${reason}`,
      },
    })
  );
}

function main() {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', c => (input += c));
  process.stdin.on('end', () => {
    let data;
    try {
      data = JSON.parse(input);
    } catch {
      process.exit(0);
    }

    if (data.hook_event_name === 'PreToolUse') {
      try {
        toolGuard(data);
      } catch {
        /* a guard failure must never block the tool call */
      }
      process.exit(0);
    }

    if (data.hook_event_name === 'PostToolUse') {
      try {
        midTurn(data);
      } catch {
        /* a malformed transcript must not disturb the tool result */
      }
      process.exit(0);
    }

    if (data.hook_event_name !== 'UserPromptSubmit') {
      if (!['SessionStart', 'SubagentStart'].includes(data.hook_event_name)) {
        process.exit(0);
      }
      console.log(readRuleFile('core', data.permission_mode) || SHORT);
      process.exit(0);
    }

    const out = [];
    try {
      out.push(...report(data));
    } catch {
      /* a malformed transcript must not block the prompt */
    }
    if (bump(data.session_id) % REMIND_EVERY === 0) out.push(SHORT);
    if (out.length) console.log(out.join('\n'));
  });
}

// require.main guards the stdin read so selftest can require ruleTargetFor
// without the module hanging on a stdin that never closes.
if (require.main === module) main();

module.exports = { ruleTargetFor, readRuleFile, fileOpReason };

// PostToolUse writes additionalContext next to the tool result, so a finding
// reaches the model while the turn is still open and the rest of the prose is
// still unwritten. Nothing blocks and no second message ships. The final message
// of a turn arrives after the last tool call, so UserPromptSubmit still has work.
//
// Two jobs. First, route a context rule file in: the tool that just ran picks
// code, prose, or commit, and each target injects once per session. Second, lint
// the prose written so far. Soft findings stay out; length is not measurable on
// half a turn.
function midTurn(data) {
  const state = loadState(data.session_id);
  const injected = state.injected || [];
  const blocks = [];

  const target = ruleTargetFor(data);
  if (target && !injected.includes(target)) {
    const text = readRuleFile(target, data.permission_mode);
    if (text) {
      blocks.push(text);
      injected.push(target);
    }
  }

  const turn = lastTurn(data.transcript_path);
  let turnKey = state.turnKey;
  let seen = state.seen || [];
  if (turn.assistant) {
    turnKey = turnId(turn);
    const priorSeen = turnKey && state.turnKey === turnKey ? state.seen || [] : [];
    const fresh = check(turn.assistant, turn.user)
      .filter(v => !v.soft)
      .filter(v => !priorSeen.includes(key(v)));
    seen = priorSeen;
    if (fresh.length) {
      const shown = fresh.slice(0, MAX_REPORTED);
      seen = [...priorSeen, ...shown.map(key)].slice(-40);
      blocks.push(
        [
          'CURT: possible editorial issues in prose earlier in this turn:',
          ...shown.map(v => `  ${DIRECTIVE[v.kind] || DIRECTIVE.default}: ${v.match} — "${v.sentence}"`),
          'Inspect these in context. Keep wording that serves the reader and ' +
            'preserves the author\'s meaning and voice. No rewrite is required ' +
            'merely to clear a match; continue the user\'s task.',
        ].join('\n')
      );
    }
  }

  if (!blocks.length) return;
  saveState(data.session_id, { ...state, turnKey, seen, injected });

  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: blocks.join('\n\n'),
      },
    })
  );
}

const key = v => `${v.kind}:${v.match}:${v.sentence}`;

// Both hooks derive the turn from the same walk, so the opening user prompt is
// the one identifier they agree on. prompt_id identifies the prompt that just
// arrived at UserPromptSubmit, and the turn on disk carries an older one.
const turnId = turn =>
  turn.user ? crypto.createHash('sha1').update(turn.user).digest('hex').slice(0, 12) : null;

function report(data) {
  const state = loadState(data.session_id);
  const turn = lastTurn(data.transcript_path);
  if (!turn.assistant) return [];
  // Each turn is reported once. Without this the same text repeats every prompt.
  if (turn.uuid && turn.uuid === state.lastUuid) return [];
  saveState(data.session_id, { ...state, lastUuid: turn.uuid });

  // A finding the PostToolUse hook already delivered stays out. The model acted
  // on it mid-turn; a repeat reads as a second offence.
  const turnKey = turnId(turn);
  const seen = turnKey && state.turnKey === turnKey ? state.seen || [] : [];
  const violations = check(turn.assistant, turn.user).filter(v => !seen.includes(key(v)));
  if (!violations.length) return [];

  // Grouped under a named directive per kind. A flat "anti-slop found 3
  // violations" reads as a log line and gets skimmed; the rule name tells the
  // model which rule it broke.
  // Sycophancy first. Truncation used to drop it behind a word-list hit, and it
  // is the finding the model most needs to see.
  const rank = {
    sycophancy: 0, verbosity: 1, phrase: 2, structure: 3, word: 4, ambiguous: 5,
  };
  const ordered = [...violations].sort(
    (a, b) => (rank[a.kind] ?? 9) - (rank[b.kind] ?? 9)
  );
  const shown = ordered.slice(0, MAX_REPORTED);
  const out = [];
  for (const kind of [...new Set(shown.map(v => v.kind))]) {
    out.push(`${DIRECTIVE[kind] || DIRECTIVE.default}: possible editorial issues in your previous message:`);
    for (const v of shown.filter(v => v.kind === kind)) {
      out.push(`  ${v.match} — "${v.sentence}"`);
    }
  }
  if (violations.length > MAX_REPORTED) {
    out.push(`  ...and ${violations.length - MAX_REPORTED} more`);
  }
  out.push(
    'These are heuristic matches. Judge them in context; keep useful wording, ' +
      'facts, qualifications, and voice. Do not rewrite or add another reply ' +
      'solely to clear a match. Continue the user\'s task.'
  );
  return out;
}

const stateFile = id => path.join(os.tmpdir(), `anti-slop-${id}.json`);

function loadState(id) {
  if (!id) return { n: 0, lastUuid: null };
  try {
    return JSON.parse(fs.readFileSync(stateFile(id), 'utf8'));
  } catch {
    return { n: 0, lastUuid: null };
  }
}

function saveState(id, state) {
  if (!id) return;
  try {
    fs.writeFileSync(stateFile(id), JSON.stringify(state));
  } catch {
    /* tmpdir not writable; the counter resets and reminds again */
  }
}

function bump(id) {
  const state = loadState(id);
  state.n = (state.n || 0) + 1;
  saveState(id, state);
  return state.n;
}
