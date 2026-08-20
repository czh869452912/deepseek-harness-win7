/**
 * User Questions Interactive Composer (`@deepseek-ai/dsh-client-ui-user-questions`)
 * Renders multi-step interactive questions with single/multi-choice, custom write-in, and pager.
 */

import { formatMarkdown, escapeHtml } from "./markdown.js";

export function parseRecommendedLabel(label) {
  const suffix = /\s*(?:\((?:recommended|推荐)\)|（(?:recommended|推荐)）)\s*$/i;
  return suffix.test(label)
    ? { label: label.replace(suffix, ""), recommended: true }
    : { label, recommended: false };
}

export class QuestionFlowView {
  constructor({ containerId = "question-composer-container", onAnswer, onCancel }) {
    this.container = document.getElementById(containerId);
    this.onAnswer = onAnswer;
    this.onCancel = onCancel;

    this.pendingQuestions = [];
    this.currentIndex = 0;
    this.drafts = [];
    this.isMinimized = false;
  }

  showQuestions(questions) {
    this.pendingQuestions = questions || [];
    this.currentIndex = 0;
    this.isMinimized = false;
    this.drafts = this.pendingQuestions.map(() => ({
      selected: [],
      custom: "",
      skipped: false,
    }));
    this.render();
  }

  hide() {
    if (this.container) {
      this.container.classList.add("hidden");
      this.container.innerHTML = "";
    }
  }

  render() {
    if (!this.container || this.pendingQuestions.length === 0) return;
    this.container.classList.remove("hidden");

    const q = this.pendingQuestions[this.currentIndex];
    const draft = this.drafts[this.currentIndex];
    const total = this.pendingQuestions.length;
    const isMulti = Boolean(q.multi_select || q.multiSelect);
    const options = q.options || [];

    let optionsHtml = "";
    options.forEach((opt, idx) => {
      const isSelected = draft.selected.includes(opt);
      const parsed = parseRecommendedLabel(opt);
      optionsHtml += `
        <button type="button" class="question-option ${isSelected ? "selected" : ""}" onclick="window._onSelectQuestionOption('${escapeHtml(opt)}')">
          <span class="option-prefix">${isMulti ? (isSelected ? "☑" : "☐") : idx + 1}</span>
          <div class="option-content">
            <span class="option-label">${escapeHtml(parsed.label)}</span>
            ${parsed.recommended ? '<span class="badge-recommended">推荐</span>' : ""}
          </div>
        </button>
      `;
    });

    // Custom input
    const customHtml = `
      <div class="question-custom-row">
        <span class="option-prefix">✎</span>
        <input type="text" class="question-custom-input" placeholder="输入其他自定义回答 (按 Enter 提交)..." value="${escapeHtml(draft.custom)}" oninput="window._onQuestionCustomInput(this.value)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();window._onQuestionNext();}">
      </div>
    `;

    this.container.innerHTML = `
      <div class="question-flow-card ${this.isMinimized ? "minimized" : ""}">
        <div class="question-flow-header">
          <div class="question-header-left">
            <span class="question-icon">❓</span>
            <span class="question-title">${escapeHtml(q.question || "请回答以下问题:")}</span>
          </div>
          <div class="question-header-actions">
            <button class="btn-icon-plain" title="${this.isMinimized ? '展开' : '折叠'}" onclick="window._onToggleMinimizeQuestion()">
              ${this.isMinimized ? "▲" : "▼"}
            </button>
            <button class="btn-icon-plain" title="取消" onclick="window._onCancelQuestions()">✕</button>
          </div>
        </div>

        ${!this.isMinimized ? `
          <div class="question-flow-body">
            ${q.detail ? `<div class="question-detail">${formatMarkdown(q.detail)}</div>` : ""}
            <div class="question-options-list">${optionsHtml}</div>
            ${customHtml}
          </div>

          <div class="question-flow-footer">
            <div class="question-pager">
              <button class="btn-pager" ${this.currentIndex === 0 ? "disabled" : ""} onclick="window._onQuestionPrev()">◀</button>
              <span class="pager-text">${this.currentIndex + 1} / ${total}</span>
              <button class="btn-pager" ${this.currentIndex === total - 1 ? "disabled" : ""} onclick="window._onQuestionNext()">▶</button>
            </div>
            <div class="question-actions">
              <button class="btn-skip" onclick="window._onQuestionSkip()">跳过 (Skip)</button>
              <button class="btn-continue" onclick="window._onQuestionContinue()">
                ${this.currentIndex === total - 1 ? "提交回答" : "下一题"}
              </button>
            </div>
          </div>
        ` : ""}
      </div>
    `;

    // Global window bridges
    window._onSelectQuestionOption = (label) => {
      if (isMulti) {
        if (draft.selected.includes(label)) {
          draft.selected = draft.selected.filter((l) => l !== label);
        } else {
          draft.selected.push(label);
        }
      } else {
        draft.selected = [label];
        draft.custom = "";
        if (this.currentIndex < total - 1) {
          this.currentIndex++;
        }
      }
      this.render();
    };

    window._onQuestionCustomInput = (val) => {
      draft.custom = val;
      if (!isMulti) draft.selected = [];
    };

    window._onQuestionPrev = () => {
      if (this.currentIndex > 0) {
        this.currentIndex--;
        this.render();
      }
    };

    window._onQuestionNext = () => {
      if (this.currentIndex < total - 1) {
        this.currentIndex++;
        this.render();
      } else {
        this.submit();
      }
    };

    window._onQuestionSkip = () => {
      draft.skipped = true;
      draft.selected = [];
      draft.custom = "";
      if (this.currentIndex < total - 1) {
        this.currentIndex++;
        this.render();
      } else {
        this.submit();
      }
    };

    window._onQuestionContinue = () => {
      if (this.currentIndex < total - 1) {
        this.currentIndex++;
        this.render();
      } else {
        this.submit();
      }
    };

    window._onToggleMinimizeQuestion = () => {
      this.isMinimized = !this.isMinimized;
      this.render();
    };

    window._onCancelQuestions = () => {
      this.hide();
      if (this.onCancel) this.onCancel();
    };
  }

  submit() {
    const formattedAnswers = this.pendingQuestions.map((q, idx) => {
      const draft = this.drafts[idx];
      if (draft.skipped) return `${q.question}: [跳过]`;
      const answers = [...draft.selected];
      if (draft.custom.trim()) answers.push(draft.custom.trim());
      return `${q.question}: ${answers.join(", ")}`;
    });

    const summaryText = formattedAnswers.join("\n");
    this.hide();
    if (this.onAnswer) this.onAnswer(summaryText);
  }
}
