/**
 * A reader for the one YAML file the archive serves, finsentry/redteam/scenarios.yml, so the site
 * needs no YAML dependency. It reads exactly the forms that file uses and nothing else: block
 * mappings and block sequences, `>-` folded text, inline `[a, b]` lists, inline `{k: v}` maps and
 * plain or double-quoted scalars. Anything else throws, so a change to the file that this reader
 * does not understand fails loudly. The tests check what it returns against the stored executions and known scenario fields.
 */

export type Yaml =
  string | number | boolean | null | Yaml[] | { [k: string]: Yaml };

interface Line {
  indent: number;
  text: string;
}

function significant(source: string): Line[] {
  const out: Line[] = [];
  for (const raw of source.split("\n")) {
    if (raw.trim() === "" || raw.trimStart().startsWith("#")) continue;
    out.push({ indent: raw.length - raw.trimStart().length, text: raw.trim() });
  }
  return out;
}

function scalar(token: string): Yaml {
  const t = token.trim();
  if (t.startsWith('"') && t.endsWith('"') && t.length >= 2) {
    return JSON.parse(t) as string;
  }
  if (t === "null" || t === "~" || t === "") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+$/.test(t)) return Number(t);
  if (/^-?\d+\.\d+$/.test(t)) return Number(t);
  return t;
}

/** Splits on commas that are outside quotes and brackets. */
function splitTop(body: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quoted = false;
  let start = 0;
  for (let i = 0; i < body.length; i += 1) {
    const ch = body[i];
    if (ch === '"' && body[i - 1] !== "\\") quoted = !quoted;
    else if (!quoted && (ch === "[" || ch === "{")) depth += 1;
    else if (!quoted && (ch === "]" || ch === "}")) depth -= 1;
    else if (!quoted && depth === 0 && ch === ",") {
      parts.push(body.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(body.slice(start));
  return parts.filter((p) => p.trim() !== "");
}

function keyIndex(text: string): number {
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    if (text[i] === '"') quoted = !quoted;
    if (
      !quoted &&
      text[i] === ":" &&
      (i === text.length - 1 || text[i + 1] === " ")
    ) {
      return i;
    }
  }
  return -1;
}

function inline(token: string): Yaml {
  const t = token.trim();
  if (t.startsWith("[") && t.endsWith("]")) {
    return splitTop(t.slice(1, -1)).map(inline);
  }
  if (t.startsWith("{") && t.endsWith("}")) {
    const out: { [k: string]: Yaml } = {};
    for (const part of splitTop(t.slice(1, -1))) {
      const at = keyIndex(part.trim());
      if (at < 0) throw new Error(`unsupported inline map entry: ${part}`);
      const p = part.trim();
      out[p.slice(0, at).trim()] = inline(p.slice(at + 1));
    }
    return out;
  }
  return scalar(t);
}

export function parseYamlSubset(source: string): Yaml {
  const lines = significant(source);
  let pos = 0;

  /** The lines of a `>-` block, folded with single spaces. */
  function folded(parentIndent: number): string {
    const parts: string[] = [];
    while (pos < lines.length && lines[pos].indent > parentIndent) {
      parts.push(lines[pos].text);
      pos += 1;
    }
    return parts.join(" ");
  }

  function value(rest: string, indent: number): Yaml {
    if (rest === ">-") return folded(indent);
    if (rest === "") {
      if (pos < lines.length && lines[pos].indent > indent) return block();
      if (
        pos < lines.length &&
        lines[pos].indent === indent &&
        lines[pos].text.startsWith("- ")
      ) {
        return block();
      }
      return null;
    }
    return inline(rest);
  }

  function block(): Yaml {
    const indent = lines[pos].indent;
    return lines[pos].text.startsWith("- ")
      ? sequence(indent)
      : mapping(indent);
  }

  function mapping(indent: number): { [k: string]: Yaml } {
    const out: { [k: string]: Yaml } = {};
    while (pos < lines.length && lines[pos].indent === indent) {
      if (lines[pos].text.startsWith("- ")) break;
      const text = lines[pos].text;
      pos += 1;
      const at = keyIndex(text);
      if (at < 0) throw new Error(`unsupported YAML line: ${text}`);
      out[text.slice(0, at).trim()] = value(text.slice(at + 1).trim(), indent);
    }
    return out;
  }

  function sequence(indent: number): Yaml[] {
    const out: Yaml[] = [];
    while (
      pos < lines.length &&
      lines[pos].indent === indent &&
      lines[pos].text.startsWith("- ")
    ) {
      const rest = lines[pos].text.slice(2).trim();
      // The mapping that starts after "- " has its keys two columns in from the dash.
      lines[pos] = { indent: indent + 2, text: rest };
      out.push(
        keyIndex(rest) >= 0 && !rest.startsWith("[") && !rest.startsWith("{")
          ? mapping(indent + 2)
          : ((pos += 1), inline(rest)),
      );
    }
    return out;
  }

  return block();
}
