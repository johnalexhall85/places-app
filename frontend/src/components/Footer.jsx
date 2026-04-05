import { APP_NAME, BRAND_FOOTER, PRIMARY_BRAND } from "../branding/pdoBrand";

export default function Footer() {
  return (
    <footer className="app-footer">
      <div className="app-footer-grid">
        <div className="app-footer-block">
          <div className="app-footer-heading">{APP_NAME}</div>
          <p>{BRAND_FOOTER.description}</p>
        </div>
        <div className="app-footer-block">
          <div className="app-footer-heading">Data Transparency</div>
          <p>{BRAND_FOOTER.transparency}</p>
        </div>
        <div className="app-footer-block">
          <div className="app-footer-heading">Source Acknowledgment</div>
          <p>{BRAND_FOOTER.sources}</p>
        </div>
      </div>
      <div className="app-footer-meta">
        <span>{PRIMARY_BRAND}</span>
        <span>Flagship data platform: CHIP</span>
      </div>
    </footer>
  );
}
