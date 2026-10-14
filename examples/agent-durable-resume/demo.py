"""Local crash/restart demo. No LLM, network API, or production writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    run_id: str
    plan: str
    receipt: str
    finished: bool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'resume', 'inspect'])
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--run-id', default='public-demo-001')
    parser.add_argument('--crash-at', choices=['before-effect', 'after-effect'])
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.data_dir / 'tool-service.sqlite'

    # Represents the TOOL SERVICE's transaction, not the agent's checkpoint.
    # Only this local fixture can commit receipt and side effect atomically.
    with sqlite3.connect(ledger_path) as db:
        db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS attempts(node TEXT PRIMARY KEY, n INTEGER);
            CREATE TABLE IF NOT EXISTS effects(
                action_id TEXT PRIMARY KEY, request_hash TEXT, receipt TEXT);
        ''')

    def attempt(node: str) -> None:
        with sqlite3.connect(ledger_path) as db:
            db.execute('INSERT INTO attempts VALUES(?,1) '
                       'ON CONFLICT(node) DO UPDATE SET n=n+1', (node,))
        print('EXECUTE ' + node, flush=True)

    def plan(state: State) -> dict:
        attempt('plan')
        return {'plan': 'Create one simulated draft, then verify its receipt.'}

    def write_draft(state: State) -> dict:
        attempt('write_draft')
        if args.crash_at == 'before-effect':
            print('CRASH before tool effect', flush=True)
            os._exit(86)
        # Stable across retries; do NOT include attempt number or new UUID.
        action_id = state['run_id'] + '/write-draft/v1'
        payload = json.dumps({'title': 'Public fixture', 'body': state['plan']},
                             sort_keys=True)
        request_hash = hashlib.sha256(payload.encode()).hexdigest()
        with sqlite3.connect(ledger_path) as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT request_hash,receipt FROM effects '
                                  'WHERE action_id=?', (action_id,)).fetchone()
            if existing:
                if existing[0] != request_hash:
                    raise ValueError('Same action_id with a different request')
                receipt = existing[1]
                print('TOOL reuse receipt ' + receipt, flush=True)
            else:
                receipt = 'draft-' + hashlib.sha256(action_id.encode()).hexdigest()[:12]
                db.execute('INSERT INTO effects VALUES(?,?,?)',
                           (action_id, request_hash, receipt))
                print('TOOL committed receipt ' + receipt, flush=True)
        if args.crash_at == 'after-effect':
            print('CRASH after effect commit, before graph checkpoint', flush=True)
            os._exit(86)
        return {'receipt': receipt}

    def finish(state: State) -> dict:
        attempt('finish')
        with sqlite3.connect(ledger_path) as db:
            row = db.execute('SELECT receipt FROM effects WHERE action_id=?',
                             (state['run_id'] + '/write-draft/v1',)).fetchone()
        if not row or row[0] != state['receipt']:
            raise ValueError('Tool receipt failed verification')
        return {'finished': True}

    builder = StateGraph(State)
    builder.add_node('plan', plan)
    builder.add_node('write_draft', write_draft)
    builder.add_node('finish', finish)
    builder.add_edge(START, 'plan')
    builder.add_edge('plan', 'write_draft')
    builder.add_edge('write_draft', 'finish')
    builder.add_edge('finish', END)
    config = {'configurable': {'thread_id': args.run_id}}
    with SqliteSaver.from_conn_string(str(args.data_dir / 'checkpoints.sqlite')) as saver:
        graph = builder.compile(checkpointer=saver)
        snapshot = graph.get_state(config)
        if args.command == 'start':
            if snapshot.values:
                raise ValueError('Run already exists; use resume or a new run_id')
            graph.invoke({'run_id': args.run_id}, config, durability='sync')
        elif args.command == 'resume':
            if not snapshot.values:
                raise ValueError('No persisted run found')
            if snapshot.next:
                # Continue the existing execution, rather than submit new input.
                graph.invoke(None, config, durability='sync')
        snapshot = graph.get_state(config)
        with sqlite3.connect(ledger_path) as db:
            counts = dict(db.execute('SELECT node,n FROM attempts'))
            effects = db.execute('SELECT COUNT(*) FROM effects').fetchone()[0]
        print(json.dumps({'next': list(snapshot.next), 'state': snapshot.values,
                          'node_executions': counts, 'tool_effects': effects},
                         ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
