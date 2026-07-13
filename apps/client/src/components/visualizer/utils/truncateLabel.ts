export function truncateLabel(text: string, maxLength = 40): string {
  if (text.length <= maxLength) return text
  return `${text.slice(0, maxLength - 3)}...`
}
