export const CLASSIFICATION_UI = Object.freeze({
  Best: { icon: "★", className: "best", label: "Best" },
  Excellent: { icon: "✓", className: "excellent", label: "Excellent" },
  Good: { icon: "●", className: "good", label: "Good" },
  Book: { icon: "▣", className: "book", label: "Book" },
  Inaccuracy: { icon: "?!", className: "inaccuracy", label: "Inaccuracy" },
  Mistake: { icon: "?", className: "mistake", label: "Mistake" },
  Miss: { icon: "!−", className: "miss", label: "Miss" },
  Blunder: { icon: "??", className: "blunder", label: "Blunder" },
  Forced: { icon: "◇", className: "forced", label: "Forced" },
});

export function classificationUi(label) {
  return CLASSIFICATION_UI[label] || null;
}

export function classificationBadge(label, extraClass = "") {
  const item = classificationUi(label);
  if (!item) return "";
  return `<span class="bishoply-classification-badge ${item.className} ${extraClass}" role="status" aria-label="${item.label}"><span class="classification-icon" aria-hidden="true">${item.icon}</span><span class="classification-label">${item.label}</span></span>`;
}
