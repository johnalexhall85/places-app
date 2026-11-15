import { useEffect, useState } from "react";
import { API_BASE } from "../config/apiBase";
import { CommunityShell, MAP_ROUTES } from "./CommunityPages";

const OVERLAY_LABELS = {
  health_centers: "HRSA health center sites",
  nursing_homes: "CMS nursing homes",
  tri_facilities: "EPA TRI reporting facilities",
};

function useTopics(slug) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    fetch(`${API_BASE}/community/topics${slug ? `/${encodeURIComponent(slug)}` : ""}`, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(response.status === 404 ? "Topic not found." : "Topics are unavailable right now.");
        return response.json();
      })
      .then(setData)
      .catch((failure) => { if (failure.name !== "AbortError") setError(failure.message); });
    return () => controller.abort();
  }, [slug]);
  return { data, error };
}

export function CommunityTopics() {
  const { data, error } = useTopics(null);
  useEffect(() => { document.title = "Topics | CHIP"; }, []);
  return <CommunityShell><div className="community-wrap community-topics-page">
    <p className="community-eyebrow">Explore by question</p>
    <h1>Community health topics</h1>
    <p>Each topic connects source-published indicators to their maps and named limits. Choose a county profile to see measures for one place.</p>
    {error && <p className="community-message" role="alert">{error}</p>}
    {!data && !error && <p className="community-message" role="status">Loading topics…</p>}
    {data && <div className="community-topic-grid">
      {data.map((topic, index) => <a className="community-topic" href={`/topics/${topic.slug}`} key={topic.slug}>
        <span className="community-topic-index">{String(index + 1).padStart(2, "0")}</span>
        <h2>{topic.title}</h2><p>{topic.summary}</p><span className="community-topic-cta">View measures and limits →</span>
      </a>)}
    </div>}
  </div></CommunityShell>;
}

export function CommunityTopic({ slug }) {
  const { data: topic, error } = useTopics(slug);
  useEffect(() => { document.title = `${topic?.title || "Topic"} | CHIP`; }, [topic]);
  return <CommunityShell><div className="community-wrap community-topic-page">
    <a className="community-back" href="/topics">← All topics</a>
    {error && <p className="community-message" role="alert">{error}</p>}
    {!topic && !error && <p className="community-message" role="status">Loading topic…</p>}
    {topic && <>
      <p className="community-eyebrow">Community health topic</p>
      <h1>{topic.title}</h1>
      <p className="community-topic-lede">{topic.summary}</p>
      <div className="community-topic-layout">
        <section aria-labelledby="topic-measures"><h2 id="topic-measures">Published measures</h2>
          {topic.measures.length ? <div className="community-topic-measures">
            {topic.measures.map((measure) => <article key={`${measure.product}:${measure.measure_id}`}>
              <h3>{measure.label}</h3>
              <p>{measure.definition}</p>
              <p className="community-source">Source: {measure.publisher} · {measure.product_name} · {measure.period}<br />Population: {measure.population} · Available at {measure.levels.join(", ")} level</p>
              {MAP_ROUTES[measure.product] && <a href={`${MAP_ROUTES[measure.product]}?measure_id=${encodeURIComponent(measure.measure_id)}`}>Open map with this measure →</a>}
            </article>)}
          </div> : <p>No released indicator is available for this topic yet. The planned measures will appear after their staging release is reviewed and published.</p>}
        </section>
        <aside aria-labelledby="topic-context"><h2 id="topic-context">Context and limits</h2>
          <p>{topic.limits}</p>
          {topic.overlays?.length > 0 && <><h3>Relevant mapped locations</h3><ul>{topic.overlays.map((overlay) => <li key={overlay}>{OVERLAY_LABELS[overlay] || overlay}</li>)}</ul>
            <p>Locations are context; they do not establish capacity, access, exposure, or cause.</p></>}
          <h3>See a place</h3>
          <p><a href="/community/county/37145">Person County, North Carolina</a> · <a href="/community/county/54039">Kanawha County, West Virginia</a> · <a href="/community/county/06019">Fresno County, California</a></p>
        </aside>
      </div>
    </>}
  </div></CommunityShell>;
}
