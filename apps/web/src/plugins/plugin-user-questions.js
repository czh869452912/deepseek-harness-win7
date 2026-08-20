/**
 * Interactive User Questions Plugin (`@deepseek-ai/dsh-client-ui-user-questions`).
 * 1:1 Implementation of Question Modal, Multi-step Pager, and POST /api/respond Resume Loop.
 */

import { QuestionFlowView } from "../ui/questions.js";
import { ApiClient } from "../connection/api.js";

export class PluginUserQuestions {
  static inject = ["slots", "sessions"];

  apply(ctx) {
    const slots = ctx.get("slots");
    const sessionsMgr = ctx.get("sessions");
    let activeQuestionFlow = null;

    // Listen to mux stream question/requested frames
    ctx.on("question/requested", (payload) => {
      const { sessionId, rpcId, questions } = payload;
      if (!questions || questions.length === 0) return;

      const container = document.getElementById("question-composer-container") || document.body;
      if (!activeQuestionFlow) {
        activeQuestionFlow = new QuestionFlowView({
          containerId: "question-composer-container",
          onAnswer: async (answerData) => {
            try {
              // Send Client-Response to POST /api/respond
              await fetch("/api/respond", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  sessionId,
                  rpcId,
                  answer: answerData,
                }),
              });
            } catch (err) {
              console.error("[UserQuestions] Failed to submit answer:", err);
            }
          },
          onCancel: async () => {
            try {
              await fetch("/api/respond", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  sessionId,
                  rpcId,
                  outcome: "cancelled",
                }),
              });
            } catch (err) {}
          },
        });
      }

      activeQuestionFlow.showQuestions(questions);
    });

    ctx.on("question/resolved", () => {
      if (activeQuestionFlow) {
        activeQuestionFlow.hide();
      }
    });
  }
}
