import { defineComponent, h, type PropType, type VNode, type VNodeChild } from "vue";
import { RouterLink } from "vue-router";
import { HEADING_ID_PREFIX, createSlugger, inlineText, parseMarkdown, type Block, type Inline } from "@/lib/markdown";
import { fragmentOf, useInPageLink } from "@/lib/inPageLink";
import { resolveRepoPath } from "@/lib/paths";
import { kindFromPath, pathSegments, viewFor } from "@/lib/format";

/**
 * Renders Markdown through Vue's h(): every piece of text is a text node, so nothing in the
 * source is ever interpreted as HTML.
 */
export default defineComponent({
  name: "MarkdownRender",
  props: {
    source: { type: String, required: true },
    /** Repo path of the document, for resolving relative links. */
    path: { type: String, default: "" },
    rev: { type: String as PropType<string | undefined>, default: undefined },
    /** Give headings GitHub-style ids (off where several documents share a page: no duplicate ids). */
    headingIds: { type: Boolean, default: true },
  },
  setup(props) {
    const inPage = useInPageLink();
    const link = (href: string, children: VNodeChild[]): VNode => {
      if (/^(https?:|mailto:)/i.test(href)) return h("a", { href, target: "_blank", rel: "noopener noreferrer" }, children);
      const fragment = fragmentOf(href);
      if (fragment !== null) return h("a", { href: inPage.href(fragment), onClick: (event: MouseEvent) => inPage.go(event, HEADING_ID_PREFIX + fragment) }, children);
      if (href.startsWith("#")) return h("span", children);
      const target = resolveRepoPath(props.path, href);
      if (!target) return h("span", children);
      const kind = kindFromPath(target);
      return h(
        RouterLink,
        { to: { name: viewFor(kind), params: { path: pathSegments(target) }, query: props.rev ? { rev: props.rev } : {} } },
        () => children,
      );
    };
    const inline = (nodes: Inline[]): VNodeChild[] =>
      nodes.map((node) => {
        switch (node.t) {
          case "text":
            return node.text;
          case "code":
            return h("code", node.text);
          case "strong":
            return h("strong", inline(node.children));
          case "em":
            return h("em", inline(node.children));
          case "link":
            return link(node.href, inline(node.children));
        }
      });
    let slug = createSlugger();
    const headingId = (node: Inline[]) => {
      const id = props.headingIds ? slug(inlineText(node)) : "";
      return id ? HEADING_ID_PREFIX + id : undefined;
    };
    const block = (node: Block): VNode => {
      switch (node.t) {
        case "heading":
          return h(`h${Math.min(6, Math.max(1, node.level))}`, { id: headingId(node.children) }, inline(node.children));
        case "paragraph":
          return h("p", inline(node.children));
        case "code":
          return h("pre", { class: "code" }, [h("code", node.text)]);
        case "quote":
          return h("blockquote", node.children.map(block));
        case "list":
          return h(node.ordered ? "ol" : "ul", node.items.map((item) => h("li", item.map(block))));
        case "table":
          return h("div", { class: "table-wrap" }, [
            h("table", { class: "data" }, [
              h("thead", [h("tr", node.header.map((cell) => h("th", inline(cell))))]),
              h("tbody", node.rows.map((row) => h("tr", row.map((cell) => h("td", inline(cell)))))),
            ]),
          ]);
        case "hr":
          return h("hr");
      }
    };
    return () => {
      slug = createSlugger();
      return h("div", { class: "markdown" }, parseMarkdown(props.source).map(block));
    };
  },
});
