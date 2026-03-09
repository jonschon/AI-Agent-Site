export function normalizeExternalUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  const cleaned = trimmed.replace(/^['"(]+|[)'",.;:!?]+$/g, "");
  if (!cleaned) return null;

  if (cleaned.startsWith("http://") || cleaned.startsWith("https://")) return cleaned;
  if (cleaned.startsWith("//")) return `https:${cleaned}`;
  return `https://${cleaned}`;
}
