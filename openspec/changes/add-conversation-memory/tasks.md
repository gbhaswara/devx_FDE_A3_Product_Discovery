Ordering follows `design.md`: the merge rule is a pure function proven before any
store exists, then the store, then the wiring, then the documentation that
currently claims memory is absent. Every group lands its own tests.

## 1. Field provenance on Criteria

- [x] 1.1 Add a `sources: frozenset[str]` field to `Criteria` recording which field names were carried from an earlier turn, defaulting to empty, and verify `describe()` is unchanged when it is empty
- [x] 1.2 Verify a test asserts that `sources` is not part of `describe()` — it is provenance for the reply, not a requirement
- [x] 1.3 Add `Criteria.describe_carried()` returning only the fields named in `sources`, and verify it returns `{}` when nothing was carried

## 2. The merge rule (pure, no store)

- [x] 2.1 Implement `merge_turn(previous, current) -> MergeResult` in `conversation.py` returning merged criteria, the carried field names, and whether the turn continued, and verify it performs no I/O
- [x] 2.2 Implement the continuation rule: a turn stating a new category, size, or product kind starts fresh; otherwise it continues, and verify each case in `design.md` D3's table as its own test
- [x] 2.3 Implement field-by-field merge where an explicit current value always wins, and verify "80 gsm then 100 gsm" yields 100 gsm
- [x] 2.4 Verify a test asserts `merge_turn(None, anything)` is a fresh request with nothing carried
- [x] 2.5 Verify a test asserts that merging never sets a field absent from both turns, so no constraint can appear from nowhere
- [x] 2.6 Verify a test asserts that merging is idempotent: merging the merged criteria again with an empty turn changes nothing

## 3. The conversation store

- [x] 3.1 Define the store protocol (`get`, `put`, `forget`, `ids`) and implement `InMemoryConversationStore` with `MAX_CONVERSATIONS` and `MAX_TURNS`, and verify both bounds are module constants read by the tests rather than literals
- [x] 3.2 Implement least-recently-used eviction when `MAX_CONVERSATIONS` is exceeded, and verify a test opens more than the maximum and asserts the oldest is gone and the count is exactly the maximum
- [x] 3.3 Implement per-conversation turn truncation at `MAX_TURNS`, and verify a test exceeds it and asserts the retained turn count while the merged criteria are unchanged
- [x] 3.4 Verify a test asserts the store holds `Criteria` and never request text
- [x] 3.5 Verify a test asserts `forget` on an unknown id is not an error and reports that nothing was forgotten
- [x] 3.6 Verify a test asserts the store is thread-safe by writing from several threads and reading a consistent state afterwards
- [x] 3.7 Implement `JsonlConversationStore` over a single append-only file with a bounded in-memory view, and verify it survives a simulated restart by reading back what a previous instance wrote
- [x] 3.8 Verify a test asserts the JSONL store never writes request text

## 4. Wiring into the assistant

- [x] 4.1 Merge in the API path between `interpret` and `validate`, and verify a two-turn conversation quotes the refined request
- [x] 4.2 Verify a test asserts the merged criteria are validated in full before pricing, and that an invalid merged value asks rather than quotes
- [x] 4.3 Render carried requirements in the reply text, naming quantity and budget explicitly rather than folding them into match reasons, and verify a test asserts both appear in the reply a salesperson reads
- [x] 4.4 Verify a test asserts a fresh request's reply says nothing about earlier turns
- [x] 4.5 Add `conversation_id` to the request model as optional, and verify a test asserts a request without it never touches the store
- [x] 4.6 Return the conversation id and the carried field names in the response, and verify a test asserts the response names them
- [x] 4.7 Add `DELETE /api/conversations/{id}` and verify a test asserts a later turn on that id is treated as fresh
- [x] 4.8 Verify a test asserts forgetting an unknown id succeeds and reports nothing forgotten
- [x] 4.9 Keep a conversation across turns on the page's fragment endpoint, and verify a test drives two turns through it and asserts the second is refined
- [x] 4.10 Verify a test asserts that with no conversation id the existing 24 evaluation cases produce byte-identical replies to the pre-change run

## 5. Records and metrics

- [x] 5.1 Add `turn_index` and `carried_fields` to the request record, omitted when there is no conversation, and verify the record's shape is unchanged for single-turn requests
- [x] 5.2 Verify a test asserts a multi-turn record states its turn index and carried fields, and a single-turn record states neither
- [x] 5.3 Verify the credential and text-capture tests still pass with conversation fields present

## 6. The CLI

- [x] 6.1 Add `--conversation <id>` to `ask`, using the JSONL store so it survives between invocations, and verify two invocations refine rather than restart
- [x] 6.2 Add `--forget` and verify a later `--conversation` with that id starts fresh
- [x] 6.3 Verify a test asserts `--conversation` writes no request text to the store file
- [x] 6.4 Verify `./run.sh ask` with no `--conversation` behaves exactly as before

## 7. Evaluation

- [x] 7.1 Add a conversation case file with at least six sequences, each asserting the merged criteria a human would have understood
- [x] 7.2 Add a case asserting a new subject mid-conversation does not inherit the old constraints
- [x] 7.3 Add a case asserting a correction mid-conversation corrects
- [x] 7.4 Add a case asserting a carried quantity is disclosed in the reply
- [x] 7.5 Add a case asserting an invalid merge asks rather than quotes
- [x] 7.6 Replay the existing 28 cases as single-turn conversations and verify each still passes, so memory cannot silently corrupt the original set
- [x] 7.7 Verify `./run.sh eval` on the original case file still reports 24/24, and on the conversation file reports its own total

## 8. Documentation

- [x] 8.1 Write `docs/conversation-memory.md`: the continuation rule and why it is conservative, the two bounds, the two stores, and that a conversation id is a label and not an authenticated session
- [x] 8.2 Update `README.md`, which currently states the assistant is single-turn
- [x] 8.3 Update `CUSTOMER_SUMMARY.md`, which currently lists conversation memory as not built
- [x] 8.4 Update `docs/chat-channel.md` §3, which currently presents the absence of memory as a deployment problem to solve later
- [x] 8.5 Verify every statement in the three updated docs matches the shipped behaviour by re-reading them against the code
- [x] 8.6 Add the new capability to the docs index and verify the index lists every doc that exists

## 9. Gates

- [x] 9.1 Verify the full suite passes offline under `unshare -rn` with no network and no credentials
- [x] 9.2 Verify `./run.sh eval` reports 24/24 on the original cases and `--self-check` exits 0
- [x] 9.3 Verify the negative control still exits 1
- [x] 9.4 Verify `./run.sh verify-refresh` still exits 0 with all 12 changes verified
- [x] 9.5 Verify `./run.sh diff` exits 0 and `./run.sh metrics --eval` still reads the most recent run
- [x] 9.6 Verify `openspec validate --all --strict` passes for every spec including the new capability
- [x] 9.7 Verify no conversation file or record file is committable, by checking `git status` after a full run
