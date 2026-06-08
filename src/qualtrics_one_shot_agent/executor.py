from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .schemas import ExecutionResult, ParsedPage, SurveyAnswer, SurveyPlan


TEXT_INPUT_SELECTOR = (
    "textarea, input[type='text'], input[type='email'], "
    "input[type='search'], input[type='tel'], input[type='url'], input:not([type])"
)
NUMBER_INPUT_SELECTOR = "input[type='number']"


CLICK_BY_VISIBLE_TEXT_JS = r"""
({answer, question, kinds}) => {
  const wanted = (answer || "").toString().replace(/\s+/g, " ").trim().toLowerCase();
  const wantedQuestion = (question || "").toString().replace(/\s+/g, " ").trim().toLowerCase();
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const textFor = (el) => {
    const parts = [el.innerText, el.textContent, el.value, el.getAttribute("aria-label"), el.getAttribute("placeholder")];
    if (el.labels) for (const label of el.labels) parts.push(label.innerText || label.textContent);
    const tag = el.tagName.toLowerCase();
    const label = el.closest("label");
    if (label) parts.push(label.innerText || label.textContent);
    if (el.id) {
      const forLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (forLabel) parts.push(forLabel.innerText || forLabel.textContent);
    }
    if (tag !== "button" && tag !== "label" && el.getAttribute("role") !== "button" && el.parentElement) {
      const parentText = norm(el.parentElement.innerText || el.parentElement.textContent);
      if (parentText.length <= 180) parts.push(parentText);
    }
    return norm(parts.filter(Boolean).join(" "));
  };
  const score = (text) => {
    if (!text || !wanted) return 0;
    if (text === wanted) return 100;
    if (text.includes(wanted)) return 80;
    if (wanted.includes(text) && text.length >= 3) return 60;
    return 0;
  };
  const contextFor = (el) => {
    const container = el.closest("fieldset,.question,tr,li,[role='group']");
    return norm(container ? (container.innerText || container.textContent) : "");
  };
  const contextScore = (text) => {
    if (!wantedQuestion || !text) return 0;
    if (text.includes(wantedQuestion)) return 80;
    const words = wantedQuestion.split(/\s+/).filter((w) => w.length >= 4);
    if (!words.length) return 0;
    const hits = words.filter((w) => text.includes(w)).length;
    return Math.min(60, Math.round((hits / words.length) * 60));
  };

  let selectors = [];
  if (kinds.includes("single_choice")) selectors.push("input[type='radio']", "[role='radio']", "label", "option", "button", "[role='button']");
  if (kinds.includes("multi_choice")) selectors.push("input[type='checkbox']", "[role='checkbox']", "label", "button", "[role='button']");
  selectors = [...new Set(selectors)];

  let best = null;
  for (const el of document.querySelectorAll(selectors.join(","))) {
    if (!visible(el)) continue;
    const text = textFor(el);
    const answerScore = score(text);
    const s = answerScore + contextScore(contextFor(el));
    if (!best || s > best.score) best = { el, score: s, answerScore, text };
  }
  if (!best || best.answerScore <= 0) return { ok: false, message: "No visible text match found" };

  let target = best.el;
  if (target.tagName.toLowerCase() === "option") {
    target.selected = true;
    target.parentElement.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, message: `Selected option: ${best.text}` };
  }
  target.click();
  return { ok: true, message: `Clicked: ${best.text}` };
}
"""


MATRIX_CLICK_JS = r"""
({row, column}) => {
  const wantedRow = (row || "").toString().replace(/\s+/g, " ").trim().toLowerCase();
  const wantedCol = (column || "").toString().replace(/\s+/g, " ").trim().toLowerCase();
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  const visible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };
  for (const table of document.querySelectorAll("table")) {
    if (!visible(table)) continue;
    const headers = [...table.querySelectorAll("thead th, tr:first-child th, tr:first-child td")].map((c) => norm(c.innerText || c.textContent));
    for (const tr of table.querySelectorAll("tr")) {
      if (!visible(tr)) continue;
      const cells = [...tr.querySelectorAll("th,td")];
      if (cells.length < 2) continue;
      const rowText = norm(cells[0].innerText || cells[0].textContent);
      if (!rowText.includes(wantedRow) && !wantedRow.includes(rowText)) continue;
      let colIndex = headers.findIndex((h) => h && (h.includes(wantedCol) || wantedCol.includes(h)));
      if (colIndex < 1) {
        colIndex = cells.findIndex((c) => norm(c.innerText || c.textContent).includes(wantedCol));
      }
      const cell = cells[colIndex];
      if (!cell) continue;
      const input = cell.querySelector("input[type='radio'], input[type='checkbox'], [role='radio'], [role='checkbox']");
      if (input && visible(input)) {
        input.click();
        return { ok: true, message: `Clicked matrix ${row} -> ${column}` };
      }
    }
  }
  return { ok: false, message: `Could not locate matrix cell ${row} -> ${column}` };
}
"""


MATRIX_COORD_CLICK_JS = r"""
({row, column}) => {
  const wantedRow = String(row || "").replace(/\s+/g, " ").trim().toLowerCase();
  const wantedCol = String(column || "").replace(/\s+/g, " ").trim().toLowerCase();
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const textNodes = [...document.querySelectorAll("body *")]
    .filter(visible)
    .map((el) => ({ el, text: norm(el.innerText || el.textContent), rect: el.getBoundingClientRect() }))
    .filter((item) => item.text && item.rect.width > 0 && item.rect.height > 0);
  const score = (text, wanted) => {
    if (text === wanted) return 100;
    if (text.includes(wanted)) return 80;
    if (wanted.includes(text) && text.length >= 4) return 60;
    return 0;
  };
  const bestFor = (wanted, preferSmall) => {
    return textNodes
      .map((item) => ({ ...item, score: score(item.text, wanted), area: item.rect.width * item.rect.height }))
      .filter((item) => item.score > 0)
      .sort((a, b) => b.score - a.score || (preferSmall ? a.area - b.area : b.area - a.area))[0];
  };
  const rowItem = bestFor(wantedRow, true);
  const colItem = bestFor(wantedCol, true);
  if (!rowItem || !colItem) {
    return { ok: false, message: `Could not find row/column text for ${row} -> ${column}` };
  }
  rowItem.el.scrollIntoView({ block: "center", inline: "center" });
  const rowRect = rowItem.el.getBoundingClientRect();
  const colRect = colItem.el.getBoundingClientRect();
  const x = colRect.left + colRect.width / 2;
  const y = rowRect.top + rowRect.height / 2;
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return { ok: false, message: `Invalid matrix coordinates for ${row} -> ${column}` };
  }
  return { ok: true, x, y, message: `Coordinate matrix click ${row} -> ${column}` };
}
"""


MATRIX_NA_CHECKBOX_JS = r"""
({row}) => {
  const wantedRow = String(row || "").replace(/\s+/g, " ").trim().toLowerCase();
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const textNodes = [...document.querySelectorAll("body *")]
    .filter(visible)
    .map((el) => ({ el, text: norm(el.innerText || el.textContent), rect: el.getBoundingClientRect() }))
    .filter((item) => item.text && item.rect.width > 0 && item.rect.height > 0);
  const score = (text, wanted) => {
    if (text === wanted) return 100;
    if (text.includes(wanted)) return 80;
    if (wanted.includes(text) && text.length >= 4) return 60;
    return 0;
  };
  const rowItem = textNodes
    .map((item) => ({ ...item, score: score(item.text, wantedRow), area: item.rect.width * item.rect.height }))
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.area - b.area)[0];
  if (!rowItem) {
    return { ok: false, message: `Could not find matrix row text for ${row}` };
  }

  rowItem.el.scrollIntoView({ block: "center", inline: "center" });
  const rowRect = rowItem.el.getBoundingClientRect();
  const rowY = rowRect.top + rowRect.height / 2;
  const labelFor = (input) => {
    const parts = [input.getAttribute("aria-label"), input.getAttribute("title")];
    if (input.labels) for (const label of input.labels) parts.push(label.innerText || label.textContent);
    const id = input.getAttribute("id");
    if (id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (explicit) parts.push(explicit.innerText || explicit.textContent);
    }
    const label = input.closest("label");
    if (label) parts.push(label.innerText || label.textContent);
    return norm(parts.filter(Boolean).join(" "));
  };
  const targetRectFor = (input) => {
    if (visible(input)) return input.getBoundingClientRect();
    if (input.labels) {
      for (const label of input.labels) {
        if (visible(label)) return label.getBoundingClientRect();
      }
    }
    const label = input.closest("label");
    if (visible(label)) return label.getBoundingClientRect();
    return null;
  };
  const targetFor = (input) => {
    if (visible(input)) return input;
    if (input.labels) {
      for (const label of input.labels) {
        if (visible(label)) return label;
      }
    }
    const label = input.closest("label");
    return visible(label) ? label : input;
  };
  const controls = [...document.querySelectorAll("input[type='checkbox'], [role='checkbox']")]
    .map((input) => ({ input, rect: targetRectFor(input), label: labelFor(input) }))
    .filter((item) => item.rect)
    .filter((item) => Math.abs((item.rect.top + item.rect.height / 2) - rowY) <= Math.max(36, rowRect.height * 1.25))
    .filter((item) => item.rect.left >= rowRect.left)
    .sort((a, b) => {
      const aLabel = /\b(n\/?a|not applicable|not heard|never heard)\b/.test(a.label) ? 1 : 0;
      const bLabel = /\b(n\/?a|not applicable|not heard|never heard)\b/.test(b.label) ? 1 : 0;
      return bLabel - aLabel || b.rect.left - a.rect.left;
    });
  if (controls.length) {
    const target = targetFor(controls[0].input);
    const rect = controls[0].rect;
    return {
      ok: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      message: `Clicked matrix ${row} -> NA`,
      targetTag: target.tagName
    };
  }

  const naText = textNodes
    .filter((item) => /^(n\/?a|not applicable)$/.test(item.text))
    .filter((item) => Math.abs((item.rect.top + item.rect.height / 2) - rowY) <= Math.max(36, rowRect.height * 1.25))
    .sort((a, b) => b.rect.left - a.rect.left)[0];
  if (naText) {
    return {
      ok: true,
      x: naText.rect.left + naText.rect.width / 2,
      y: naText.rect.top + naText.rect.height / 2,
      message: `Clicked matrix ${row} -> NA label`
    };
  }
  return { ok: false, message: `Could not find NA checkbox for matrix row ${row}` };
}
"""


SET_RANGE_JS = r"""
({value}) => {
  const target = Number(value);
  if (!Number.isFinite(target)) {
    return { ok: false, message: `Slider answer is not numeric: ${value}` };
  }
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
  const ranges = [...document.querySelectorAll("input[type='range']")].filter(visible);
  if (!ranges.length) {
    return { ok: false, message: "No visible range input found" };
  }
  const el = ranges[0];
  const min = el.min === "" ? 0 : Number(el.min);
  const max = el.max === "" ? 100 : Number(el.max);
  const clamped = Math.min(Math.max(target, min), max);
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  nativeSetter.call(el, String(clamped));
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  return { ok: true, message: `Set slider to ${clamped}`, value: clamped, min, max };
}
"""


PAGE_STATE_JS = r"""
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
  const warningPattern = /(please answer|required|unanswered|must answer|must select|validation|invalid|incomplete|missing|error)/i;
  const validation_messages = [];
  for (const el of document.querySelectorAll("[role='alert'],[aria-live],.ValidationError,.QuestionValidationError,.QErrorMessage,.ErrorMessage,.error,.warning,[class*='alidation'],[class*='Error'],[id*='Error'],[id*='Validation']")) {
    if (!visible(el)) continue;
    const text = norm(el.innerText || el.textContent);
    if (text && warningPattern.test(text) && !validation_messages.includes(text)) validation_messages.push(text);
  }
  const dialogs = [];
  for (const el of document.querySelectorAll("[role='dialog'],[aria-modal='true'],.ui-dialog,.modal,.Modal,.Dialog,.Popup,.Q_Window")) {
    if (!visible(el)) continue;
    const text = norm(el.innerText || el.textContent);
    if (text) dialogs.push(text);
  }
  return {
    url: window.location.href,
    visible_text: norm(document.body ? document.body.innerText : ""),
    validation_messages,
    dialogs
  };
}
"""


SET_RANK_JS = r"""
({items}) => {
  const wanted = Array.isArray(items) ? items.map((x) => String(x).replace(/\s+/g, " ").trim()).filter(Boolean) : [];
  if (!wanted.length) return { ok: false, message: "Rank answer did not contain an ordered list" };
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const setSelectValue = (select, rank) => {
    const rankText = String(rank);
    const option = [...select.options].find((o) => norm(o.value) === rankText || norm(o.textContent) === rankText || norm(o.textContent).startsWith(rankText));
    if (!option) return false;
    select.value = option.value;
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  };
  const containers = [...document.querySelectorAll("li,tr,div,label")].filter(visible);
  const actions = [];
  const used = new Set();

  for (let index = 0; index < wanted.length; index += 1) {
    const item = wanted[index];
    const itemNorm = norm(item);
    const rank = index + 1;
    let matches = containers
      .filter((el) => !used.has(el) && norm(el.innerText || el.textContent).includes(itemNorm) && el.querySelector("select"))
      .sort((a, b) => norm(a.innerText || a.textContent).length - norm(b.innerText || b.textContent).length);
    let container = matches[0];
    if (!container) continue;
    const select = [...container.querySelectorAll("select")].find(visible);
    if (select && setSelectValue(select, rank)) {
      used.add(container);
      actions.push(`Ranked ${item} as ${rank}`);
    }
  }
  if (actions.length === wanted.length) return { ok: true, message: "Set rank dropdowns", actions };

  const selects = [...document.querySelectorAll("select")].filter(visible);
  if (selects.length >= wanted.length) {
    const fallbackActions = [];
    for (let index = 0; index < wanted.length; index += 1) {
      if (!setSelectValue(selects[index], index + 1)) {
        return { ok: false, message: `Could not set rank option ${index + 1}` };
      }
      fallbackActions.push(`Set rank dropdown ${index + 1}`);
    }
    return { ok: true, message: "Set rank dropdowns by visible order", actions: fallbackActions };
  }

  return { ok: false, message: "No visible rank dropdowns found" };
}
"""


UNANSWERED_REQUIRED_JS = r"""
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
  const textFor = (el) => norm(el.innerText || el.textContent || el.getAttribute("aria-label") || el.name || "");
  const missing = [];
  for (const input of [...document.querySelectorAll("[required]")].filter(visible)) {
    if ((input.type || "").toLowerCase() === "checkbox") {
      if (!input.checked) missing.push(textFor(input.closest("label") || input));
    } else if (!String(input.value || "").trim()) {
      missing.push(textFor(input.closest("label") || input));
    }
  }
  for (const group of [...document.querySelectorAll("[data-required-group]")].filter(visible)) {
    const name = group.dataset.requiredGroup;
    if (name && !group.querySelector(`input[name="${CSS.escape(name)}"]:checked`)) missing.push(textFor(group));
  }
  for (const group of [...document.querySelectorAll("[data-required-checkbox]")].filter(visible)) {
    const name = group.dataset.requiredCheckbox;
    if (name && !group.querySelector(`input[name="${CSS.escape(name)}"]:checked`)) missing.push(textFor(group));
  }
  return [...new Set(missing.filter(Boolean))];
}
"""


SELECT_BY_TEXT_JS = r"""
({answer}) => {
  const wanted = String(answer || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
  for (const select of [...document.querySelectorAll("select")].filter(visible)) {
    if (select.value && !select.multiple) continue;
    const option = [...select.options].find((o) => !o.disabled && (norm(o.textContent) === wanted || norm(o.value) === wanted || norm(o.textContent).includes(wanted)));
    if (!option) continue;
    if (select.multiple) {
      option.selected = true;
    } else {
      select.value = option.value;
    }
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    return { ok: true, message: `Selected dropdown option: ${option.textContent.trim()}` };
  }
  return { ok: false, message: "No empty visible select matched requested option" };
}
"""


FIND_CUSTOM_SELECT_INDEX_JS = r"""
({question}) => {
  const wantedQuestion = String(question || "").replace(/\s+/g, " ").trim().toLowerCase();
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim().toLowerCase();
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
  const contextFor = (el) => {
    const container = el.parentElement ? el.parentElement.closest("fieldset,.question,.QuestionOuter,.QuestionBody,.q-question,li,tr,div") : null;
    return norm(container ? (container.innerText || container.textContent) : "");
  };
  const contextScore = (text) => {
    if (!wantedQuestion || !text) return 0;
    if (text.includes(wantedQuestion)) return 100;
    const words = wantedQuestion.split(/\s+/).filter((w) => w.length >= 4);
    if (!words.length) return 0;
    const hits = words.filter((w) => text.includes(w)).length;
    return Math.round((hits / words.length) * 80);
  };
  const allTriggers = [...document.querySelectorAll(
    "[role='combobox'],[aria-haspopup='listbox']"
  )].filter((el) => {
    if (!visible(el)) return false;
    const text = norm(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
    const role = el.getAttribute("role");
    const hasPopup = el.getAttribute("aria-haspopup") === "listbox";
    return role === "combobox" || hasPopup || text === "select one" || text === "select" || text.includes("select one");
  });
  let best = null;
  for (let index = 0; index < allTriggers.length; index += 1) {
    const el = allTriggers[index];
    const text = norm(el.innerText || el.textContent || el.getAttribute("aria-label") || "");
    const score = contextScore(contextFor(el)) + (text.includes("select") ? 10 : 0);
    if (!best || score > best.score) best = { index, score, text };
  }
  if (!best) return { ok: false, message: "No visible custom dropdown trigger found" };
  return { ok: true, index: best.index, message: `Found custom dropdown: ${best.text}` };
}
"""


def execute_plan(
    page: Page,
    plan: SurveyPlan,
    parsed_page: ParsedPage,
    action_interval_seconds: float = 0.0,
) -> ExecutionResult:
    actions: list[str] = []
    errors: list[str] = []

    if plan.status == "finished":
        return ExecutionResult(status="finished", message="LLM marked survey finished")
    if plan.status == "stuck":
        return ExecutionResult(status="stuck", message=plan.stuck_reason or "LLM marked page stuck")

    for answer in plan.answers:
        result = _execute_answer(page, answer)
        actions.extend(result.actions)
        errors.extend(result.errors)
        if result.status == "stuck":
            return ExecutionResult(
                status="stuck",
                message=result.message,
                actions=actions,
                errors=errors,
            )
        _wait_action_interval(page, action_interval_seconds)

    if plan.next == "stop":
        return ExecutionResult(status="ok", message="Answered page and did not click next", actions=actions, errors=errors)

    _wait_action_interval(page, action_interval_seconds)
    missing_required = _visible_unanswered_required(page)
    if missing_required:
        actions.append("Visible required follow-up appeared after answering; deferring next click")
        return ExecutionResult(
            status="ok",
            message="Visible required follow-up appeared after answering; waiting for next decision loop",
            actions=actions,
            errors=errors,
        )

    next_result = click_next(page, parsed_page)
    actions.extend(next_result.actions)
    errors.extend(next_result.errors)
    return ExecutionResult(
        status=next_result.status,
        message=next_result.message,
        actions=actions,
        errors=errors,
    )


def _wait_action_interval(page: Page, seconds: float) -> None:
    if seconds <= 0:
        return
    try:
        page.wait_for_timeout(int(seconds * 1000))
    except Exception:
        pass


def _execute_answer(page: Page, answer: SurveyAnswer) -> ExecutionResult:
    if answer.answer_type == "single_choice":
        result = _click_choice(page, answer.question_id_or_text, str(answer.answer), "single_choice")
        if result.status == "ok":
            return result
        select_result = _select_options(page, answer.question_id_or_text, answer.answer)
        if select_result.status == "ok":
            return select_result
        return ExecutionResult(
            status="stuck",
            message=result.message,
            actions=result.actions + select_result.actions,
            errors=result.errors + select_result.errors,
        )
    if answer.answer_type == "multi_choice":
        if not isinstance(answer.answer, list):
            return ExecutionResult(status="stuck", message="multi_choice answer must be a list")
        actions = []
        for item in answer.answer:
            result = _click_choice(page, answer.question_id_or_text, str(item), "multi_choice")
            actions.extend(result.actions)
            if result.status == "stuck":
                select_result = _select_options(page, answer.question_id_or_text, answer.answer)
                if select_result.status == "ok":
                    return select_result
                return ExecutionResult(status="stuck", message=result.message, actions=actions, errors=result.errors + select_result.errors)
        return ExecutionResult(status="ok", message="Clicked multi_choice answers", actions=actions)
    if answer.answer_type == "text":
        return _fill_text(page, str(answer.answer))
    if answer.answer_type == "number":
        return _fill_number(page, answer.answer)
    if answer.answer_type == "select":
        return _select_options(page, answer.question_id_or_text, answer.answer)
    if answer.answer_type == "matrix":
        return _execute_matrix(page, answer.answer)
    if answer.answer_type == "slider":
        return _execute_slider(page, answer.answer)
    if answer.answer_type == "rank":
        return _execute_rank(page, answer.answer)
    return ExecutionResult(status="stuck", message=f"Unsupported answer type: {answer.answer_type}")


def _click_choice(page: Page, question_text: str, answer_text: str, kind: str) -> ExecutionResult:
    try:
        result = page.evaluate(CLICK_BY_VISIBLE_TEXT_JS, {"answer": answer_text, "question": question_text, "kinds": [kind]})
        if result.get("ok"):
            page.wait_for_timeout(150)
            return ExecutionResult(status="ok", message=result["message"], actions=[result["message"]])
        return ExecutionResult(status="stuck", message=result.get("message", "Choice click failed"))
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Choice click failed: {exc}", errors=[str(exc)])


def _fill_text(page: Page, value: str) -> ExecutionResult:
    locator = page.locator(TEXT_INPUT_SELECTOR)
    try:
        count = locator.count()
        for index in range(count):
            field = locator.nth(index)
            if not field.is_visible() or not field.is_enabled():
                continue
            current = ""
            try:
                current = field.input_value()
            except Exception:
                pass
            if current.strip():
                continue
            field.fill(value)
            page.wait_for_timeout(150)
            return ExecutionResult(status="ok", message="Filled visible text field", actions=["Filled visible text field"])
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Text fill failed: {exc}", errors=[str(exc)])
    return ExecutionResult(status="stuck", message="No empty visible text input or textarea found")


def _fill_number(page: Page, value: Any) -> ExecutionResult:
    if isinstance(value, dict):
        values = [item_value for item_key, item_value in value.items() if str(item_key).strip().lower() != "total"]
        return _fill_multiple_numbers(page, values)
    if isinstance(value, list):
        return _fill_multiple_numbers(page, value)
    number = _extract_number(value)
    if number is None:
        return ExecutionResult(status="stuck", message=f"Could not extract numeric input value from answer: {value!r}")
    locator = page.locator(NUMBER_INPUT_SELECTOR)
    try:
        count = locator.count()
        for index in range(count):
            field = locator.nth(index)
            if not field.is_visible() or not field.is_enabled():
                continue
            current = ""
            try:
                current = field.input_value()
            except Exception:
                pass
            if current.strip():
                continue
            field.fill(str(int(number) if number.is_integer() else number))
            page.wait_for_timeout(150)
            return ExecutionResult(status="ok", message=f"Filled number field with {number}", actions=[f"Filled number field with {number}"])
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Number fill failed: {exc}", errors=[str(exc)])
    fallback = _fill_text(page, str(int(number) if number.is_integer() else number))
    if fallback.status == "ok":
        return ExecutionResult(
            status="ok",
            message=f"Filled text field with numeric value {number}",
            actions=[f"Filled text field with numeric value {number}"],
        )
    return ExecutionResult(status="stuck", message="No empty visible number or text input found for numeric answer")


def _fill_multiple_numbers(page: Page, values: list[Any]) -> ExecutionResult:
    numeric_values = []
    for value in values:
        number = _extract_number(value)
        if number is not None:
            numeric_values.append(str(int(number) if number.is_integer() else number))
    if not numeric_values:
        return ExecutionResult(status="stuck", message=f"Could not extract numeric values from answer: {values!r}")

    locator = page.locator(f"{NUMBER_INPUT_SELECTOR}, input[type='text'], input:not([type])")
    actions: list[str] = []
    try:
        count = locator.count()
        value_index = 0
        for index in range(count):
            if value_index >= len(numeric_values):
                break
            field = locator.nth(index)
            if not field.is_visible() or not field.is_enabled():
                continue
            current = ""
            try:
                current = field.input_value()
            except Exception:
                pass
            if current.strip():
                continue
            field.fill(numeric_values[value_index])
            actions.append(f"Filled numeric field with {numeric_values[value_index]}")
            value_index += 1
            page.wait_for_timeout(80)
        if value_index == len(numeric_values):
            return ExecutionResult(status="ok", message="Filled multiple numeric fields", actions=actions)
        return ExecutionResult(status="stuck", message=f"Only filled {value_index} of {len(numeric_values)} numeric values", actions=actions)
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Multiple number fill failed: {exc}", actions=actions, errors=[str(exc)])


def _select_options(page: Page, question_text: str, answer: Any) -> ExecutionResult:
    if isinstance(answer, dict):
        values = [(str(key), str(value)) for key, value in answer.items()]
    elif isinstance(answer, list):
        values = [(question_text, str(value)) for value in answer]
    else:
        values = [(question_text, str(answer))]
    actions: list[str] = []
    for field_text, value in values:
        result = _select_option(page, field_text, value)
        actions.extend(result.actions)
        if result.status == "stuck":
            return ExecutionResult(status="stuck", message=result.message, actions=actions, errors=result.errors)
    return ExecutionResult(status="ok", message="Selected dropdown option(s)", actions=actions)


def _select_option(page: Page, question_text: str, answer_text: str) -> ExecutionResult:
    try:
        result = page.evaluate(SELECT_BY_TEXT_JS, {"answer": answer_text})
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Select execution failed: {exc}", errors=[str(exc)])
    if result.get("ok"):
        page.wait_for_timeout(150)
        return ExecutionResult(status="ok", message=result["message"], actions=[result["message"]])
    return _select_custom_option(page, question_text, answer_text, result.get("message", "Native select execution failed"))


def _select_custom_option(page: Page, question_text: str, answer_text: str, native_message: str) -> ExecutionResult:
    try:
        found = page.evaluate(FIND_CUSTOM_SELECT_INDEX_JS, {"question": question_text})
        if not found.get("ok"):
            return ExecutionResult(status="stuck", message=f"{native_message}; {found.get('message', 'custom dropdown not found')}")
        page.locator("[role='combobox'],[aria-haspopup='listbox']").nth(int(found["index"])).click(timeout=3000)
        page.wait_for_timeout(250)
        option = _visible_option_locator(page, answer_text) or _visible_text_locator(page, answer_text)
        if option is None:
            return ExecutionResult(status="stuck", message=f"{native_message}; opened custom dropdown but option was not visible: {answer_text}")
        option.click(timeout=3000)
        page.wait_for_timeout(250)
        return ExecutionResult(status="ok", message=f"Selected custom dropdown option: {answer_text}", actions=[f"Selected custom dropdown option: {answer_text}"])
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Custom select execution failed: {exc}", errors=[str(exc)])


def _execute_matrix(page: Page, answer: Any) -> ExecutionResult:
    if not isinstance(answer, dict):
        return ExecutionResult(status="stuck", message="matrix answer must be an object mapping row text to column answer")
    actions = []
    errors = []
    for row, column in answer.items():
        if _matrix_answer_is_na(column):
            na_result = _matrix_na_checkbox_click(page, str(row))
            if na_result.status == "ok":
                actions.extend(na_result.actions)
                continue
            errors.extend(na_result.errors)
        try:
            result = page.evaluate(MATRIX_CLICK_JS, {"row": str(row), "column": str(column)})
        except Exception as exc:
            return ExecutionResult(status="stuck", message=f"Matrix click failed: {exc}", actions=actions, errors=[str(exc)])
        if not result.get("ok"):
            coord_result = _matrix_coordinate_click(page, str(row), str(column))
            if coord_result.status == "stuck":
                errors.append(result.get("message", "Matrix click failed"))
                errors.extend(coord_result.errors)
                return ExecutionResult(status="stuck", message=coord_result.message, actions=actions, errors=errors)
            actions.extend(coord_result.actions)
            continue
        actions.append(result["message"])
    return ExecutionResult(status="ok", message="Answered matrix", actions=actions, errors=errors)


def _matrix_answer_is_na(value: Any) -> bool:
    text = str(value or "").strip().lower()
    compact = re.sub(r"[^a-z0-9]+", "", text)
    return (
        compact in {"na", "nslasha", "notapplicable"}
        or compact.startswith("na")
        or "notheard" in compact
        or "neverheard" in compact
        or "haventheard" in compact
        or "havenotheard" in compact
    )


def _matrix_na_checkbox_click(page: Page, row: str) -> ExecutionResult:
    try:
        result = page.evaluate(MATRIX_NA_CHECKBOX_JS, {"row": row})
        if not result.get("ok"):
            return ExecutionResult(status="stuck", message=result.get("message", "Matrix NA checkbox click failed"))
        page.mouse.click(float(result["x"]), float(result["y"]))
        page.wait_for_timeout(150)
        return ExecutionResult(status="ok", message=result["message"], actions=[result["message"]])
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Matrix NA checkbox click failed: {exc}", errors=[str(exc)])


def _matrix_coordinate_click(page: Page, row: str, column: str) -> ExecutionResult:
    try:
        result = page.evaluate(MATRIX_COORD_CLICK_JS, {"row": row, "column": column})
        if not result.get("ok"):
            return ExecutionResult(status="stuck", message=result.get("message", "Matrix coordinate click failed"))
        page.mouse.click(float(result["x"]), float(result["y"]))
        page.wait_for_timeout(150)
        return ExecutionResult(status="ok", message=result["message"], actions=[result["message"]])
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Matrix coordinate click failed: {exc}", errors=[str(exc)])


def _execute_slider(page: Page, answer: Any) -> ExecutionResult:
    value = _extract_number(answer)
    if value is None:
        return ExecutionResult(status="stuck", message=f"Could not extract numeric slider value from answer: {answer!r}")
    try:
        result = page.evaluate(SET_RANGE_JS, {"value": value})
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Slider execution failed: {exc}", errors=[str(exc)])
    if result.get("ok"):
        page.wait_for_timeout(150)
        return ExecutionResult(status="ok", message=result["message"], actions=[result["message"]])
    return ExecutionResult(status="stuck", message=result.get("message", "Slider execution failed"))


def _execute_rank(page: Page, answer: Any) -> ExecutionResult:
    items = _extract_rank_items(answer)
    if not items:
        return ExecutionResult(status="stuck", message=f"Could not extract ordered rank items from answer: {answer!r}")
    try:
        result = page.evaluate(SET_RANK_JS, {"items": items})
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Rank execution failed: {exc}", errors=[str(exc)])
    if result.get("ok"):
        actions = result.get("actions") or [result.get("message", "Set rank")]
        return ExecutionResult(status="ok", message=result.get("message", "Set rank"), actions=actions)

    drag_result = _drag_rank_items(page, items)
    if drag_result.status == "ok":
        return drag_result
    return ExecutionResult(
        status="stuck",
        message=f"{result.get('message', 'Rank dropdown execution failed')}; {drag_result.message}",
        actions=drag_result.actions,
        errors=drag_result.errors,
    )


def _extract_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        return float(match.group(0)) if match else None
    if isinstance(value, dict):
        for key in ("value", "answer", "target", "position"):
            if key in value:
                extracted = _extract_number(value[key])
                if extracted is not None:
                    return extracted
    return None


def _extract_rank_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        pieces = [piece.strip(" .") for piece in re.split(r"\s*(?:,|>|;|\n)\s*", value) if piece.strip(" .")]
        return pieces if len(pieces) > 1 else []
    if isinstance(value, dict):
        if "order" in value:
            return _extract_rank_items(value["order"])
        if "items" in value:
            return _extract_rank_items(value["items"])
        sortable: list[tuple[float, str]] = []
        for item, rank in value.items():
            number = _extract_number(rank)
            if number is not None:
                sortable.append((number, str(item).strip()))
        if sortable:
            return [item for _, item in sorted(sortable) if item]
    return []


def _drag_rank_items(page: Page, items: list[str]) -> ExecutionResult:
    actions: list[str] = []
    try:
        for target_index, item in enumerate(items):
            source = _visible_text_locator(page, item)
            if source is None:
                return ExecutionResult(status="stuck", message=f"Could not find visible rank item: {item}", actions=actions)
            source_box = source.bounding_box()
            if source_box is None:
                return ExecutionResult(status="stuck", message=f"Could not locate rank item box: {item}", actions=actions)

            current_items = [_visible_text_locator(page, existing) for existing in items]
            boxes = [locator.bounding_box() if locator is not None else None for locator in current_items]
            visible_boxes = [box for box in boxes if box is not None]
            if len(visible_boxes) < len(items):
                return ExecutionResult(status="stuck", message="Could not locate all rank item boxes", actions=actions)
            ordered_boxes = sorted(visible_boxes, key=lambda box: (box["y"], box["x"]))
            target_box = ordered_boxes[target_index]
            page.mouse.move(source_box["x"] + source_box["width"] / 2, source_box["y"] + source_box["height"] / 2)
            page.mouse.down()
            page.mouse.move(target_box["x"] + target_box["width"] / 2, target_box["y"] + target_box["height"] / 2, steps=8)
            page.mouse.up()
            page.wait_for_timeout(150)
            actions.append(f"Dragged rank item {item} to position {target_index + 1}")
        return ExecutionResult(status="ok", message="Dragged rank items into requested order", actions=actions)
    except Exception as exc:
        return ExecutionResult(status="stuck", message=f"Rank drag execution failed: {exc}", actions=actions, errors=[str(exc)])


def _visible_text_locator(page: Page, text: str):
    exact = page.get_by_text(text, exact=True)
    try:
        for index in range(exact.count()):
            candidate = exact.nth(index)
            if candidate.is_visible():
                return candidate
    except Exception:
        pass
    pattern = re.compile(re.escape(text), re.IGNORECASE)
    fuzzy = page.get_by_text(pattern)
    try:
        for index in range(fuzzy.count()):
            candidate = fuzzy.nth(index)
            if candidate.is_visible():
                return candidate
    except Exception:
        pass
    return None


def _visible_option_locator(page: Page, text: str):
    pattern = re.compile(rf"^\s*{re.escape(text)}\s*$", re.IGNORECASE)
    option = page.get_by_role("option", name=pattern)
    try:
        for index in range(option.count()):
            candidate = option.nth(index)
            if candidate.is_visible():
                return candidate
    except Exception:
        pass
    return None


def click_next(page: Page, parsed_page: ParsedPage) -> ExecutionResult:
    if _parsed_page_has_unanswered_dialog(parsed_page):
        return ExecutionResult(
            status="ok",
            message="Validation/reminder dialog is visible; no automatic continue click performed",
            actions=["Validation/reminder dialog is visible; waiting for next decision loop"],
        )

    is_continue_gate = _visible_text_suggests_continue(parsed_page.visible_text)
    if is_continue_gate:
        _wait_for_continue_gate_runtime(page)

    next_pattern = re.compile(r"\b(next|continue|submit|done|finish)\b", re.IGNORECASE)
    arrow_pattern = re.compile(r"^\s*(→|➜|➔|›|>)\s*$")
    if is_continue_gate:
        candidates = [
            lambda: page.locator("#NextButton").click(timeout=5000),
            lambda: page.get_by_role("button", name=arrow_pattern).last.click(timeout=3000),
            lambda: page.locator("button,input[type='submit'],input[type='button'],[role='button']").filter(has_text=arrow_pattern).last.click(timeout=3000),
        ]
    else:
        candidates = [
            lambda: page.get_by_role("button", name=next_pattern).click(timeout=3000),
            lambda: page.get_by_text(next_pattern).last.click(timeout=3000),
            lambda: page.locator("input[type='submit'], input[type='button'], button").filter(has_text=next_pattern).last.click(timeout=3000),
        ]
    for click in candidates:
        try:
            before = _current_page_state(page)
            click()
            if is_continue_gate:
                _wait_for_continue_gate_to_advance(page, before)
            else:
                _wait_after_click(page)
                _wait_for_navigation_or_stable(page, before)
            after = _current_page_state(page)
            actions = ["Clicked next/continue/submit"]
            if _has_prompt_or_validation(after):
                actions.append("Validation/reminder is visible after clicking next")
                return ExecutionResult(
                    status="ok",
                    message="Clicked next; validation/reminder remains visible for the next decision loop",
                    actions=actions,
                )
            if before["url"] == after["url"] and _compact_text(before["visible_text"]) == _compact_text(after["visible_text"]):
                actions.append("Page appeared unchanged after clicking next")
                if is_continue_gate:
                    return ExecutionResult(
                        status="stuck",
                        message="Continue gate did not advance after clicking the arrow button",
                        actions=actions,
                    )
            return ExecutionResult(status="ok", message="Clicked next/continue/submit", actions=actions)
        except Exception:
            continue

    visible_lower = parsed_page.visible_text.lower()
    finished_markers = ["thank you", "completed", "complete", "submitted", "survey is finished"]
    if any(marker in visible_lower for marker in finished_markers):
        return ExecutionResult(status="finished", message="No next button found and page appears to be an ending page")
    return ExecutionResult(status="stuck", message="No visible Next/Continue/Submit/Done button found")


def _visible_text_suggests_continue(text: str) -> bool:
    return bool(
        re.search(
            r"click the button to continue|continue to the survey|begin the survey|start the survey",
            text or "",
            re.IGNORECASE,
        )
    )


def _wait_for_continue_gate_runtime(page: Page) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except PlaywrightTimeoutError:
        pass
    try:
        page.wait_for_function(
            """
            () => document.readyState === "complete" &&
              Boolean(document.querySelector("#NextButton")) &&
              Boolean(window.Qualtrics && window.Qualtrics.SurveyEngine)
            """,
            timeout=8000,
        )
    except PlaywrightTimeoutError:
        pass
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass


def _wait_for_continue_gate_to_advance(page: Page, before: dict[str, Any]) -> None:
    before_text = _compact_text(str(before.get("visible_text", "")))
    try:
        page.wait_for_function(
            """
            (beforeText) => {
              const compact = (s) => (s || "").replace(/\\s+/g, " ").trim().slice(0, 2000);
              const text = compact(document.body ? document.body.innerText : "");
              const stillGate = /click the button to continue|continue to the survey|begin the survey|start the survey/i.test(text);
              return text && text !== beforeText && !stillGate;
            }
            """,
            arg=before_text,
            timeout=18000,
        )
    except PlaywrightTimeoutError:
        pass
    _wait_after_click(page)


def _current_page_state(page: Page) -> dict[str, Any]:
    try:
        return page.evaluate(PAGE_STATE_JS)
    except Exception:
        return {"url": page.url, "visible_text": "", "validation_messages": [], "dialogs": []}


def _has_prompt_or_validation(state: dict[str, Any]) -> bool:
    if state.get("validation_messages"):
        return True
    prompt_pattern = re.compile(r"(unanswered|required|please answer|continue without|incomplete|missing)", re.IGNORECASE)
    return any(prompt_pattern.search(str(text)) for text in state.get("dialogs", []))


def _parsed_page_has_unanswered_dialog(parsed_page: ParsedPage) -> bool:
    prompt_pattern = re.compile(r"(unanswered|required|please answer|continue without|incomplete|missing)", re.IGNORECASE)
    return any(prompt_pattern.search(str(dialog.get("text", ""))) for dialog in parsed_page.dialogs)


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:2000]


def _visible_unanswered_required(page: Page) -> list[str]:
    try:
        return page.evaluate(UNANSWERED_REQUIRED_JS)
    except Exception:
        return []


def _wait_after_click(page: Page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        pass
    try:
        page.wait_for_timeout(500)
    except Exception:
        pass


def _wait_for_navigation_or_stable(page: Page, before: dict[str, Any]) -> None:
    try:
        page.wait_for_function(
            """
            (beforeText) => {
              const compact = (s) => (s || "").replace(/\\s+/g, " ").trim().slice(0, 2000);
              const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
              };
              const text = compact(document.body ? document.body.innerText : "");
              const disabledNext = [...document.querySelectorAll("button,[role='button'],input[type='button'],input[type='submit']")]
                .filter(visible)
                .some((el) => /next|continue|submit|done|finish/i.test(el.innerText || el.value || el.getAttribute("aria-label") || "") &&
                  (el.disabled || el.getAttribute("aria-disabled") === "true"));
              const obviousSpinner = [...document.querySelectorAll("[aria-busy='true'],.spinner,.loading,.Loading,.Progress,.progress")]
                .some(visible);
              return text !== beforeText || (!disabledNext && !obviousSpinner);
            }
            """,
            arg=_compact_text(str(before.get("visible_text", ""))),
            timeout=8000,
        )
    except PlaywrightTimeoutError:
        pass
