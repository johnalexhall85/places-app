import { useEffect, useMemo, useState } from "react";
import logoMonochromeSmall from "../assets/brand/chip-logo-monochrome-dark-small.svg";

const NAV_ITEMS = [
  {
    id: "about",
    label: "About",
    heading: "About CHIP",
    text: "Community Health Intelligence Platform (CHIP) helps local teams explore public health patterns and respond with practical action.",
  },
  {
    id: "data-sources",
    label: "Data Sources",
    heading: "Data Sources",
    text: "CHIP combines modeled PLACES indicators with additional public datasets so communities can compare risks and context from multiple perspectives.",
  },
  {
    id: "methodology",
    label: "Methodology",
    heading: "Methodology",
    text: "Each indicator is tied to a documented method and confidence context so decisions can stay transparent and reproducible.",
  },
  {
    id: "download",
    label: "Download",
    heading: "Download",
    text: "Export options for maps, summary profiles, and supporting visuals are available through the panel actions across the app.",
  },
  {
    id: "help",
    label: "Help",
    heading: "Help",
    text: "Use Search to locate an area, select a measure in Measure controls, and use the CHIP Intelligence Assistant for guided interpretation.",
  },
];

export default function Header() {
  const [activeNavId, setActiveNavId] = useState(null);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const activeNavItem = useMemo(
    () => NAV_ITEMS.find((item) => item.id === activeNavId) ?? null,
    [activeNavId]
  );

  useEffect(() => {
    const onEscape = (event) => {
      if (event.key !== "Escape") return;
      setActiveNavId(null);
      setMobileMenuOpen(false);
    };
    window.addEventListener("keydown", onEscape);
    return () => {
      window.removeEventListener("keydown", onEscape);
    };
  }, []);

  const handleNavClick = (id) => {
    setActiveNavId(id);
    setMobileMenuOpen(false);
  };

  return (
    <>
      <header className="chip-header">
        <div className="chip-header-brand">
          <img
            src={logoMonochromeSmall}
            alt="Community Health Intelligence Platform logo"
            className="chip-header-logo"
          />
          <span className="chip-header-wordmark">CHIP</span>
        </div>

        <button
          type="button"
          className="chip-menu-button"
          aria-label="Toggle navigation menu"
          aria-expanded={mobileMenuOpen}
          onClick={() => setMobileMenuOpen((current) => !current)}
        >
          Menu
        </button>

        <nav className={`chip-header-nav ${mobileMenuOpen ? "is-open" : ""}`}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              type="button"
              className="chip-header-link"
              onClick={() => handleNavClick(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      {activeNavItem ? (
        <div
          className="chip-nav-modal-backdrop"
          onClick={() => setActiveNavId(null)}
          role="presentation"
        >
          <div
            className="chip-nav-modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`chip-nav-heading-${activeNavItem.id}`}
          >
            <div className="chip-nav-modal-header">
              <h2 id={`chip-nav-heading-${activeNavItem.id}`}>{activeNavItem.heading}</h2>
              <button
                type="button"
                className="chip-nav-modal-close"
                onClick={() => setActiveNavId(null)}
                aria-label="Close"
              >
                Close
              </button>
            </div>
            <p>{activeNavItem.text}</p>
          </div>
        </div>
      ) : null}
    </>
  );
}
