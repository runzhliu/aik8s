"""Pinned M3.1 template fix: inspect the final assistant prefix, not system examples.

The official template documents <mm:think></mm:think> inside the system prompt.
The shipped parser mistakes those documentation tokens for completed reasoning
when initializing an SSE stream. Preserve its generated-token extraction.
"""
from vllm.reasoning import ReasoningParserManager
from vllm.reasoning.minimax_m3_reasoning_parser import MiniMaxM3ReasoningParser

class MiniMaxM31PromptScopedParser(MiniMaxM3ReasoningParser):
    def is_reasoning_end(self, input_ids):
        text=self._decode_text(input_ids)
        marker=']~b]ai\n'
        position=text.rfind(marker)
        if position>=0:
            suffix=text[position+len(marker):]
            if not suffix:return False
            return super().is_reasoning_end(self._encode_text(suffix))
        return super().is_reasoning_end(input_ids)

ReasoningParserManager.register_module(name='minimax_m3',module=MiniMaxM31PromptScopedParser,force=True)
