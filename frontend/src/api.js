async function call(path, body) {
  const r = await fetch("/api" + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d?.message || "Request failed");
  }
  return data;
}
export const api = {
  health: () => call("/health"),
  sample: () => call("/sample"),
  generate: (material) => call("/generate", { material }),
  regenerate: (material, type, id) => call("/regenerate", { material, type, id }),
  validate: (material, question) => call("/validate", { material, question }),
  exportTagged: (material, questions) => call("/export", { material, questions }),
};
