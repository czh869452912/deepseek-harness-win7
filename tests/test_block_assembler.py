import pytest
from dsh.core.agent_loop import BlockAssembler


def test_block_assembler_text_and_tool_calls():
    assembler = BlockAssembler()
    assembler.push({"delta": {"content": "Hello "}})
    assembler.push({"delta": {"content": "world!"}})
    assembler.push({
        "delta": {
            "tool_calls": [
                {"id": "call-1", "function": {"name": "pwsh", "arguments": '{"command": "dir"}'}}
            ]
        }
    })

    blocks = assembler.blocks()
    assert len(blocks) == 2
    assert blocks[0] == {"type": "text", "text": "Hello world!"}
    assert blocks[1] == {"type": "tool-call", "id": "call-1", "name": "pwsh", "arguments": '{"command": "dir"}'}


def test_block_assembler_interrupted():
    assembler = BlockAssembler()
    assembler.push({"delta": {"content": "Partial output"}})
    interrupted = assembler.interrupted_blocks()
    assert len(interrupted) == 1
    assert interrupted[0]["text"] == "Partial output"
