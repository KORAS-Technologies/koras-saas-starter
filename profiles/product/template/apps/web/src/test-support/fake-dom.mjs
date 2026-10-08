/**
 * The smallest DOM `react-dom/client` needs to mount, update and unmount a
 * tree of plain elements, so a component can be rendered and re-rendered
 * under `node --test` with no browser and no extra dependency.
 *
 * It is a data structure with the DOM's mutation surface (create, append,
 * insert, remove, attributes, text) and nothing else: no layout, no events
 * delivered, no CSS. Enough to assert what is on the page after a render;
 * not enough to click. A test that needs a click belongs in Playwright.
 */

const ELEMENT_NODE = 1
const TEXT_NODE = 3
const COMMENT_NODE = 8
const DOCUMENT_NODE = 9
const SVG = 'http://www.w3.org/2000/svg'
const HTML = 'http://www.w3.org/1999/xhtml'

function rootOf(node) {
  while (node.parentNode !== null) node = node.parentNode
  return node
}

class Node {
  constructor(ownerDocument) {
    this.ownerDocument = ownerDocument
    this.parentNode = null
    this.childNodes = []
  }

  get firstChild() {
    return this.childNodes[0] ?? null
  }

  get lastChild() {
    return this.childNodes[this.childNodes.length - 1] ?? null
  }

  get nextSibling() {
    if (this.parentNode === null) return null
    const siblings = this.parentNode.childNodes
    return siblings[siblings.indexOf(this) + 1] ?? null
  }

  get previousSibling() {
    if (this.parentNode === null) return null
    const siblings = this.parentNode.childNodes
    return siblings[siblings.indexOf(this) - 1] ?? null
  }

  get parentElement() {
    const parent = this.parentNode
    return parent !== null && parent.nodeType === ELEMENT_NODE ? parent : null
  }

  get isConnected() {
    return rootOf(this).nodeType === DOCUMENT_NODE
  }

  appendChild(child) {
    return this.insertBefore(child, null)
  }

  insertBefore(child, before) {
    if (child.parentNode !== null) child.parentNode.removeChild(child)
    const index = before === null ? this.childNodes.length : this.childNodes.indexOf(before)
    if (index === -1) throw new Error('insertBefore: the reference node is not a child')
    this.childNodes.splice(index, 0, child)
    child.parentNode = this
    return child
  }

  removeChild(child) {
    const index = this.childNodes.indexOf(child)
    if (index === -1) throw new Error('removeChild: the node is not a child')
    this.childNodes.splice(index, 1)
    child.parentNode = null
    return child
  }

  contains(other) {
    for (let node = other; node !== null; node = node.parentNode) if (node === this) return true
    return false
  }

  addEventListener() {}

  removeEventListener() {}

  dispatchEvent() {
    return true
  }

  get textContent() {
    return this.childNodes.map((child) => child.textContent).join('')
  }

  set textContent(text) {
    for (const child of this.childNodes) child.parentNode = null
    this.childNodes = []
    if (text !== '' && text !== null && text !== undefined) {
      this.appendChild(this.ownerDocument.createTextNode(String(text)))
    }
  }
}

class Text extends Node {
  constructor(ownerDocument, data) {
    super(ownerDocument)
    this.nodeType = TEXT_NODE
    this.nodeName = '#text'
    this.nodeValue = data
  }

  get data() {
    return this.nodeValue
  }

  set data(value) {
    this.nodeValue = String(value)
  }

  get textContent() {
    return this.nodeValue
  }

  set textContent(value) {
    this.nodeValue = String(value)
  }
}

class Comment extends Node {
  constructor(ownerDocument, data) {
    super(ownerDocument)
    this.nodeType = COMMENT_NODE
    this.nodeName = '#comment'
    this.nodeValue = data
  }

  get textContent() {
    return ''
  }
}

class Element extends Node {
  constructor(ownerDocument, tagName, namespaceURI) {
    super(ownerDocument)
    this.nodeType = ELEMENT_NODE
    this.namespaceURI = namespaceURI
    this.localName = tagName
    this.tagName = namespaceURI === SVG ? tagName : tagName.toUpperCase()
    this.nodeName = this.tagName
    this.attributes = new Map()
    this.style = { setProperty: (name, value) => { this.style[name] = value } }
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value))
  }

  setAttributeNS(_namespace, name, value) {
    this.setAttribute(name, value)
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null
  }

  hasAttribute(name) {
    return this.attributes.has(name)
  }

  removeAttribute(name) {
    this.attributes.delete(name)
  }

  get className() {
    return this.getAttribute('class') ?? ''
  }

  set className(value) {
    this.setAttribute('class', value)
  }

  get id() {
    return this.getAttribute('id') ?? ''
  }

  get children() {
    return this.childNodes.filter((child) => child.nodeType === ELEMENT_NODE)
  }

  /**
   * `react-dom`'s own `<select>` commit path (`updateOptions`, called on
   * every mount and every re-render of a controlled select) reads
   * `node.options` as a live, indexable list of `<option>` elements and
   * assigns their `.selected`/`.defaultSelected` directly -- it does not go
   * through `setAttribute` the way most props do. A real `HTMLSelectElement`
   * exposes exactly that; this element does not otherwise distinguish tag
   * types, so `options` is defined narrowly, only for a `<select>` itself,
   * rather than widening `Element` with browser behaviour nothing else here
   * needs (E18-F03-S01, the first test in this repo to mount a real
   * `SelectField` with options rather than a hand-rolled listbox).
   */
  get options() {
    return this.localName === 'select'
      ? this.children.filter((child) => child.localName === 'option')
      : undefined
  }

  /**
   * `react-dom` writes an `<option>`'s `value` prop with `setAttribute`
   * (the same generic path as most non-form attributes -- see
   * `setInitialDOMProperties`'s `case "value"`), never as a property
   * assignment. `updateOptions` (the getter just above) then reads it back
   * as `node[i].value`, exactly as a real `HTMLOptionElement.value` IDL
   * getter would: the attribute if set, the element's own text otherwise.
   * Without this, every option's `.value` reads back `undefined`, no
   * option's value ever equals the controlling `<select>`'s current value,
   * and `updateOptions`'s own fallback always marks the first option
   * selected regardless of state -- silently wrong rather than a thrown
   * error, so this one is easy to miss.
   *
   * Every other element keeps a plain `value` property (an ordinary
   * getter/setter pair over `_value`, behaviourally identical to the bare
   * property `Element` used before -- `<input>`/`<textarea>` still get
   * `.value` written directly by `react-dom`, unaffected by this).
   */
  get value() {
    if (this.localName === 'option') {
      return this.hasAttribute('value') ? this.getAttribute('value') : this.textContent
    }
    return this._value
  }

  set value(next) {
    this._value = next
  }

  /**
   * A real `HTMLOptionElement.selected` setter runs the HTML spec's
   * "selectedness setting algorithm": for a single (non-`multiple`) select,
   * selecting one option deselects every sibling. `react-dom`'s own
   * `updateOptions` (see the `options` getter above) relies on exactly that
   * -- it sets `.selected = true` on the one option that now matches the
   * controlled value and simply returns, trusting the platform to have
   * already cleared the previous selection; it never explicitly clears
   * anything itself. A plain property here would leave every
   * previously-selected option still marked selected, which is how the
   * first version of this getter/setter pair (a bare `_selected` property)
   * let `selectedValue()` in `AccountDetailPanel.test.mjs` observe *two*
   * "selected" options after a change and, on the next render, quietly
   * revert to the first rather than the one just chosen -- found by an
   * actual failing test (E18-F03-S01), not by inspection.
   */
  get selected() {
    return this._selected === true
  }

  set selected(next) {
    this._selected = Boolean(next)
    if (!this._selected || this.localName !== 'option') return
    let ancestor = this.parentNode
    while (ancestor !== null && ancestor.localName !== 'select') ancestor = ancestor.parentNode
    if (ancestor === null || ancestor.multiple) return
    for (const option of ancestor.options) {
      if (option !== this) option._selected = false
    }
  }

  /** Every descendant element, in document order. */
  *descendants() {
    for (const child of this.childNodes) {
      if (child.nodeType !== ELEMENT_NODE) continue
      yield child
      yield* child.descendants()
    }
  }

  /** `[data-testid="<id>"]`, the one selector the tests use. */
  byTestId(id) {
    return [...this.descendants()].filter((element) => element.getAttribute('data-testid') === id)
  }

  /**
   * Like a browser's: a disabled control cannot take focus, and the one that
   * can becomes `document.activeElement`. A call that does nothing is exactly
   * how focus was lost in the import panel, so the tests must be able to see it.
   */
  focus() {
    if (this.disabled === true || this.getAttribute('disabled') !== null) return
    this.ownerDocument.activeElement = this
  }

  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = null
  }
}

class Document extends Node {
  constructor() {
    super(null)
    this.ownerDocument = this
    this.nodeType = DOCUMENT_NODE
    this.nodeName = '#document'
    this.activeElement = null
    // What `react-dom` asks of the window around a document: whether the
    // focused element is a frame. Nothing here ever is.
    this.defaultView = { document: this, HTMLIFrameElement: class HTMLIFrameElement {} }
    this.documentElement = this.createElement('html')
    this.body = this.createElement('body')
    this.documentElement.appendChild(this.body)
    this.appendChild(this.documentElement)
  }

  createElement(tagName) {
    return new Element(this, tagName, HTML)
  }

  createElementNS(namespaceURI, tagName) {
    return new Element(this, tagName, namespaceURI)
  }

  createTextNode(data) {
    return new Text(this, String(data))
  }

  createComment(data) {
    return new Comment(this, String(data))
  }
}

// `react-dom` reads `window.event` to pick an update priority, and
// `next/link` reaches for `self.requestIdleCallback` before it falls back to
// a timer. A `window` with no `document` keeps React's "can use DOM" switch
// off, so nothing else in either assumes a browser.
if (typeof globalThis.window === 'undefined') globalThis.window = globalThis
if (typeof globalThis.self === 'undefined') globalThis.self = globalThis

// `AccountDetailPanel` (E18-F04-S01) calls `window.history.replaceState` to
// drop `?saved=...` from the URL once its one-time notice has been read, and
// reads `window.location.pathname` to do so. No test before it exercised the
// `saved !== null` branch, so neither existed here -- a minimal,
// side-effect-free stub is added rather than in the component: a real
// browser's address bar is not observable from this harness anyway, so all
// this needs to do is not throw and remember the last state it was given.
if (typeof globalThis.window.location === 'undefined') {
  globalThis.window.location = { pathname: '/' }
}
if (typeof globalThis.window.history === 'undefined') {
  globalThis.window.history = {
    state: null,
    replaceState(state) {
      this.state = state
    },
  }
}

/** A fresh document and a container already attached to its body. */
export function createContainer() {
  const document = new Document()
  const container = document.createElement('div')
  document.body.appendChild(container)
  return container
}
