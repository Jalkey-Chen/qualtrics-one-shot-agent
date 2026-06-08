from __future__ import annotations

from playwright.sync_api import Page

from .schemas import ParsedPage


PARSER_JS = r"""
() => {
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const hasHiddenAncestor = (el) => {
    for (let node = el; node && node.nodeType === Node.ELEMENT_NODE; node = node.parentElement) {
      if (node.getAttribute("aria-hidden") === "true") return true;
      const style = window.getComputedStyle(node);
      if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return true;
    }
    return false;
  };
  const visible = (el) => {
    if (!el || hasHiddenAncestor(el)) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const labelText = (el) => {
    const pieces = [];
    if (el.labels) {
      for (const label of el.labels) pieces.push(label.innerText || label.textContent || "");
    }
    if (el.id) {
      const forLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (forLabel) pieces.push(forLabel.innerText || forLabel.textContent || "");
    }
    const closestLabel = el.closest("label");
    if (closestLabel) pieces.push(closestLabel.innerText || closestLabel.textContent || "");
    pieces.push(el.getAttribute("aria-label") || "");
    pieces.push(el.getAttribute("placeholder") || "");
    pieces.push(el.value || "");
    pieces.push(el.innerText || el.textContent || "");
    const parent = el.parentElement;
    const tag = el.tagName.toLowerCase();
    if (parent && tag !== "button" && tag !== "label" && el.getAttribute("role") !== "button") {
      const parentText = norm(parent.innerText || parent.textContent || "");
      if (parentText.length <= 180) pieces.push(parentText);
    }
    return norm([...new Set(pieces.map(norm).filter(Boolean))].join(" | "));
  };
  const cssish = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = el.getAttribute("type");
    const role = el.getAttribute("role");
    const name = el.getAttribute("name");
    return { tag, type, role, name };
  };

  const fields = [];
  const fieldEls = document.querySelectorAll(
    "button,input,textarea,select,[role='button'],[role='radio'],[role='checkbox'],[role='combobox'],[role='listbox'],[role='option'],[aria-haspopup='listbox']"
  );
  for (const el of fieldEls) {
    if (!visible(el)) continue;
    if (el.tagName.toLowerCase() === "input" && (el.type || "").toLowerCase() === "hidden") continue;
    const meta = cssish(el);
    const item = {
      ...meta,
      text: labelText(el),
      checked: Boolean(el.checked),
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
      value: el.value || null,
      min: el.getAttribute("min"),
      max: el.getAttribute("max"),
      step: el.getAttribute("step"),
      options: []
    };
    if (el.tagName.toLowerCase() === "select") {
      item.options = [...el.options].filter((o) => !o.disabled).map((o) => norm(o.textContent || o.value));
    }
    fields.push(item);
  }

  const groups = [];
  const groupedInputs = new Map();
  for (const field of fields) {
    if (!["radio", "checkbox"].includes((field.type || "").toLowerCase())) continue;
    const groupName = field.name || field.text || `${field.type}_unnamed`;
    if (!groupedInputs.has(groupName)) {
      groupedInputs.set(groupName, {
        kind: field.type === "radio" ? "radio_group" : "checkbox_group",
        name: groupName,
        options: []
      });
    }
    groupedInputs.get(groupName).options.push({
      text: field.text,
      value: field.value,
      checked: field.checked,
      disabled: field.disabled
    });
  }
  for (const group of groupedInputs.values()) groups.push(group);
  for (const field of fields) {
    const tag = (field.tag || "").toLowerCase();
    const type = (field.type || "").toLowerCase();
    if (tag === "select") {
      groups.push({ kind: "select", name: field.name || field.text || "select", text: field.text, options: field.options, value: field.value });
    } else if (field.role === "combobox" || field.role === "listbox" || field.role === "option" || /select one/i.test(field.text || "")) {
      groups.push({ kind: "custom_select", name: field.name || field.text || "custom_select", text: field.text, options: field.options || [], value: field.value });
    } else if (tag === "textarea" || ["text", "email", "number", "search", "tel", "url"].includes(type) || (tag === "input" && !type)) {
      groups.push({ kind: type === "number" ? "number_input" : "text_input", name: field.name || field.text || field.placeholder, text: field.text, value: field.value, min: field.min, max: field.max });
    } else if (type === "range") {
      groups.push({ kind: "range_slider", name: field.name || field.text || "range", text: field.text, value: field.value, min: field.min, max: field.max, step: field.step });
    }
  }

  const bodyText = norm(document.body ? document.body.innerText : "");
  const nextWords = ["next", "continue", "submit", "done", "finish"];
  const arrowOnly = /^(→|➜|➔|›|>|→\s*)$/;
  const bodySuggestsContinue = /click the button to continue|continue to the survey|begin the survey|start the survey/i.test(bodyText);
  const next_button_candidates = fields
    .filter((f) => ["button", "submit", "button"].includes((f.type || f.tag || "").toLowerCase()) || f.role === "button")
    .filter((f) => nextWords.some((word) => (f.text || "").toLowerCase().includes(word)) || (bodySuggestsContinue && arrowOnly.test(f.text || "")));

  const matrices = [];
  for (const table of document.querySelectorAll("table")) {
    if (!visible(table)) continue;
    const headerCells = [...table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")];
    const columns = headerCells.slice(1).map((c) => norm(c.innerText || c.textContent)).filter(Boolean);
    const rows = [];
    for (const tr of table.querySelectorAll("tr")) {
      if (!visible(tr)) continue;
      const cells = [...tr.querySelectorAll("th,td")];
      if (cells.length < 2) continue;
      const rowText = norm(cells[0].innerText || cells[0].textContent);
      if (rowText) rows.push(rowText);
    }
    if (columns.length && rows.length) matrices.push({ columns, rows });
  }

  const warningPattern = /(please answer|required|unanswered|must answer|must select|validation|invalid|incomplete|missing|error)/i;
  const validation_messages = [];
  const validationEls = document.querySelectorAll(
    "[role='alert'],[aria-live],.ValidationError,.QuestionValidationError,.QErrorMessage,.ErrorMessage,.error,.warning,[class*='alidation'],[class*='Error'],[id*='Error'],[id*='Validation']"
  );
  for (const el of validationEls) {
    if (!visible(el)) continue;
    const text = norm(el.innerText || el.textContent);
    if (text && warningPattern.test(text) && !validation_messages.includes(text)) {
      validation_messages.push(text);
    }
  }
  for (const sentence of bodyText.split(/(?<=[.!?])\s+/)) {
    const text = norm(sentence);
    if (text && text.length <= 300 && warningPattern.test(text) && !validation_messages.includes(text)) {
      validation_messages.push(text);
    }
  }

  const dialogs = [];
  const dialogEls = document.querySelectorAll("[role='dialog'],[aria-modal='true'],.ui-dialog,.modal,.Modal,.Dialog,.Popup,.Q_Window");
  for (const el of dialogEls) {
    if (!visible(el)) continue;
    const buttons = [...el.querySelectorAll("button,input[type='button'],input[type='submit'],[role='button']")]
      .filter(visible)
      .map((button) => norm(button.innerText || button.textContent || button.value || button.getAttribute("aria-label")))
      .filter(Boolean);
    const text = norm(el.innerText || el.textContent);
    if (text) dialogs.push({ text, buttons });
  }

  return {
    url: window.location.href,
    visible_text: bodyText,
    fields,
    groups,
    next_button_candidates,
    validation_messages,
    dialogs,
    matrices
  };
}
"""


def parse_page(page: Page) -> ParsedPage:
    data = page.evaluate(PARSER_JS)
    return ParsedPage.model_validate(data)
