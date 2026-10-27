function normalize(text) {
    const chars = [];
    const boundaries = [0];
    for (let index = 0; index < text.length; index++) {
        if (text[index] === '\r') {
            if (text[index + 1] === '\n')
                index++;
            chars.push('\n');
        }
        else
            chars.push(text[index]);
        boundaries.push(index + 1);
    }
    return { text: chars.join(''), boundaries };
}
function boundary(text, index) {
    if (!Number.isInteger(index) || index < 0 || index > text.length)
        return false;
    const before = text.charCodeAt(index - 1), after = text.charCodeAt(index);
    return !(before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff);
}
function indexOfBoundary(items, value) {
    let left = 0, right = items.length - 1;
    while (left <= right) {
        const middle = (left + right) >>> 1;
        if (items[middle] === value)
            return middle;
        if (items[middle] < value)
            left = middle + 1;
        else
            right = middle - 1;
    }
    return -1;
}
let cached;
function coordinates(source, editor) {
    if (cached?.source === source && cached.editor === editor)
        return cached;
    const points = [0];
    for (const point of source)
        points.push(points[points.length - 1] + point.length);
    cached = { source, editor, raw: normalize(source), view: normalize(editor), points };
    return cached;
}
/** Only newline representation may differ; never guess among duplicate quotes. */
export function mapEditorRange(source, editor, start, end) {
    if (end <= start || !boundary(editor, start) || !boundary(editor, end))
        return null;
    const { raw, view, points } = coordinates(source, editor);
    if (raw.text !== view.text)
        return null;
    const left = indexOfBoundary(view.boundaries, start), right = indexOfBoundary(view.boundaries, end);
    if (left < 0 || right < 0)
        return null; // A CRLF pair cannot be split.
    const rawStart = raw.boundaries[left], rawEnd = raw.boundaries[right];
    return {
        start: indexOfBoundary(points, rawStart),
        end: indexOfBoundary(points, rawEnd),
        text: source.slice(rawStart, rawEnd),
    };
}
/** Translate stored source code-point hints back into the editor's UTF-16 view. */
export function mapSourceRange(source, editor, start, end) {
    const { raw, view, points } = coordinates(source, editor);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || end <= start || end >= points.length)
        return null;
    if (raw.text !== view.text)
        return null;
    const rawStart = points[start], rawEnd = points[end];
    const left = indexOfBoundary(raw.boundaries, rawStart), right = indexOfBoundary(raw.boundaries, rawEnd);
    if (left < 0 || right < 0)
        return null;
    const viewStart = view.boundaries[left], viewEnd = view.boundaries[right];
    return { start: viewStart, end: viewEnd, text: editor.slice(viewStart, viewEnd) };
}
