import type { SignalContextItem, SignalEvaluationContext } from '@roostorg/coop-types';
import { MAX_CLASSIFY_TEXT_LENGTH } from './constants.js';

function messageText(data: Readonly<Record<string, unknown>>): string | undefined {
  const isText = (value: unknown): value is string => typeof value === 'string' && value.trim() !== '';
  for (const key of ['text', 'body', 'content', 'message']) {
    const value = data[key];
    if (isText(value)) return value.trim();
  }
  return Object.values(data).find(isText)?.trim();
}

function creatorLabel(item: SignalContextItem): string {
  return (item.creator?.id || 'unknown').replace(/[\r\n\]]/g, ' ');
}

function renderMessage(message: SignalContextItem): string | undefined {
  const text = messageText(message.data);
  return text === undefined ? undefined : `[${creatorLabel(message)}]: ${text}`;
}

function sameItem(a: SignalContextItem | undefined, b: SignalContextItem): boolean {
  return a !== undefined && a.itemId === b.itemId && a.itemTypeId === b.itemTypeId;
}

function compose(parentLine: string | undefined, history: readonly string[], text: string): string {
  const sections: string[] = [];
  if (parentLine !== undefined) sections.push(parentLine);
  if (history.length > 0) {
    sections.push(`Earlier messages in this thread (oldest first):\n${history.join('\n')}`);
  }
  if (sections.length === 0) return text;
  return `${sections.join('\n\n')}\n\nMessage to evaluate:\n${text}`;
}

/**
 * Builds the text sent to Pigeon from the item's text plus whatever context
 * Coop loaded (per the org's Evaluation context settings):
 *
 *   In reply to [<creator id>]: <parent text>
 *
 *   Earlier messages in this thread (oldest first):
 *   [<creator id>]: <message text>
 *
 *   Message to evaluate:
 *   <item text>
 *
 * The item and its parent are not repeated in the thread history. Coop doesn't
 * trim context by size, so the plugin enforces Pigeon's 100,000-character
 * limit: oldest thread messages are dropped first; the parent and the item are
 * kept, and if even those don't fit, only the item's text is sent.
 */
export function buildClassifyText(
  text: string,
  context: SignalEvaluationContext | undefined,
): string {
  if (text.length > MAX_CLASSIFY_TEXT_LENGTH || context === undefined) return text;

  const parentText = context.parent ? messageText(context.parent.data) : undefined;
  const parentLine =
    context.parent && parentText !== undefined
      ? `In reply to [${creatorLabel(context.parent)}]: ${parentText}`
      : undefined;

  let history = (context.thread?.messages ?? [])
    .filter((message) => !sameItem(context.item, message) && !sameItem(context.parent, message))
    .map(renderMessage)
    .filter((line): line is string => line !== undefined);

  for (;;) {
    const result = compose(parentLine, history, text);
    if (result.length <= MAX_CLASSIFY_TEXT_LENGTH) return result;
    if (history.length === 0) return text;
    history = history.slice(1);
  }
}
