import { useEffect, useRef, useState } from "react";
import pdoMark from "../assets/brand/pdo-observatory-mark.png";
import { useDemoAccess } from "../demoAccess/DemoAccessGate";
import { isFundingModelBuilderEnabled } from "../utils/fundingModelBuilderAccess";
import "./SiteHeader.css";

export const SITE_NAV = [
  { href: "/", label: "Home" },
  { href: "/topics", label: "Topics" },
  { href: "/compare", label: "Compare" },
  { href: "/districts", label: "Districts" },
  { href: "/explore/map", label: "Explore data" },
  { href: "/cdc-funding", label: "Funding" },
  { href: "/ai", label: "Use CHIP with AI" },
  { href: "/about", label: "About" },
];

export const SITE_HEADER_FALLBACK_HEIGHT = 88;

// One header for every page. Fixed-height map pages read its measured height
// from --chip-header-height, because the navigation wraps on narrow screens.
export default function SiteHeader() {
  const ref = useRef(null);
  const { hasAccess, logout } = useDemoAccess();

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const publish = () => {
      const height = Math.round(node.getBoundingClientRect().height);
      if (height > 0) document.documentElement.style.setProperty("--chip-header-height", `${height}px`);
    };
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <>
      <a className="community-skip" href="#main">Skip to main content</a>
      <header className="community-header" ref={ref}>
        <a className="community-brand" href="/" aria-label="CHIP home">
          <img src={pdoMark} alt="" width="44" height="44" />
          <span><strong>PUBLIC DATA OBSERVATORY</strong><small>CHIP · Community Health Intelligence Platform</small></span>
        </a>
        <nav aria-label="Main navigation">
          {SITE_NAV.map((item) => <a href={item.href} key={item.href}>{item.label}</a>)}
          {isFundingModelBuilderEnabled() && <a href="/funding-model-builder">Funding Model Builder</a>}
          {hasAccess && <button type="button" className="community-header-logout" onClick={() => logout()}>Log out</button>}
        </nav>
      </header>
    </>
  );
}

// Measured header height for pages that size a map in JavaScript.
export function useSiteHeaderHeight() {
  const [height, setHeight] = useState(SITE_HEADER_FALLBACK_HEIGHT);
  useEffect(() => {
    const node = document.querySelector(".community-header");
    if (!node || typeof ResizeObserver === "undefined") return undefined;
    const read = () => {
      const next = Math.round(node.getBoundingClientRect().height);
      if (next > 0) setHeight(next);
    };
    read();
    const observer = new ResizeObserver(read);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return height;
}
