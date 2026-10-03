# Working with local models on offensive tasks

Practical discipline, learned mostly by getting it wrong.

## Where they help

Transformation tasks, where the input is in front of the model and you can
check the output:

- turning raw scanner output into a prioritised list
- reading code in a language or codebase you do not know
- translating intent between tool syntaxes
- turning technical output into prose a client can read

## Where they do not

Judgment tasks, where the input is incomplete and the output is a decision:

- whether an action is safe to take against a live target
- whether a bounds check is correct
- how confident to be about anything

## The failure mode is fluency

A local model's wrong answers come out in the same register as its right ones.
Nothing in the tone separates a verified observation from an invention, so you
cannot triage the output without redoing the work.

Design around it:

- require citations to specific addresses, paths or line numbers
- prefer claims that came from a tool call you can inspect
- treat any confidence rating as uncalibrated
- check boundary arithmetic by hand, always

## Prompting that actually helps

- Ask for observation and inference to be separated explicitly.
- Ask what would settle an uncertain question, not how confident it is.
- Tell it that absence of evidence from one tool is not evidence of absence.
  This measurably reduces "no strings found, therefore no secrets."
- Give it a way to say it does not know, or it will fill the space.

## Context is the scarce resource

A full disassembly will fill a local model's window and evict the instructions
along with everything else. The symptom is drift: repeated tool calls,
forgotten goals, conclusions unrelated to the evidence.

Work function by function. Truncate tool output and say that you truncated it.
Cap the number of steps so a confused run ends instead of grinding on.

## Keep a transcript

Every claim worth acting on should be traceable to a tool call. A transcript
turns "the model said" into "here is what it observed and when," which is the
difference between a lead and a finding.
