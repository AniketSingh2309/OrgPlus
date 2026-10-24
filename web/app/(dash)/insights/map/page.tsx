"use client";

import { Minus, Plus, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ComposableMap, Geographies, Geography, Marker, ZoomableGroup } from "react-simple-maps";
import world from "world-atlas/countries-110m.json";
import { usePalette } from "@/components/charts";
import { BarList, Card, Chip, DataTable, Empty, ErrorState, PageHeader, PageSkeleton } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Data = {
  points: { lat: number; lon: number; city: string | null; country: string | null; signins: number; users: number; failures: number }[];
  countries: { country: string; signins: number; users: number; failures: number }[];
  new_locations: { user: string; country: string; first_seen: string }[];
  geoip: boolean;
};

type Point = Data["points"][number];
type View = { center: [number, number]; zoom: number };

/** Start zoomed to where 90% of sign-ins happen, so a few far-off ones don't force a world view. */
function initialView(points: Point[]): View {
  if (!points.length) return { center: [60, 20], zoom: 1 };
  const total = points.reduce((n, pt) => n + pt.signins, 0);
  const core: Point[] = [];
  let covered = 0;
  for (const pt of [...points].sort((a, b) => b.signins - a.signins)) {
    core.push(pt);
    covered += pt.signins;
    if (covered >= total * 0.9) break;
  }
  const lons = core.map((pt) => pt.lon);
  const lats = core.map((pt) => pt.lat);
  const [minLon, maxLon, minLat, maxLat] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const span = Math.max(maxLon - minLon, (maxLat - minLat) * 2, 8); // never closer than ~8 degrees
  return {
    center: [(minLon + maxLon) / 2, (minLat + maxLat) / 2],
    zoom: Math.min(12, Math.max(1, 220 / (span + 12))),
  };
}

export default function MapPage() {
  const { data, error, mutate } = useApi<Data>("/insights/signin-map");
  const p = usePalette();
  const [hover, setHover] = useState<Point | null>(null);
  const fitted = useMemo(() => initialView(data?.points ?? []), [data?.points]);
  const [view, setView] = useState<View>(fitted);
  const [userMoved, setUserMoved] = useState(false);
  // Follow new data (live refresh) until the viewer pans or zooms themselves.
  useEffect(() => {
    if (!userMoved) setView(fitted);
  }, [fitted, userMoved]);
  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!data) return <PageSkeleton />;
  const max = Math.max(...data.points.map((x) => x.signins), 1);

  return (
    <>
      <PageHeader title="Sign-in map" subtitle="Where people signed in from, last 30 days" />
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Sign-in locations" subtitle={hover ? `${[hover.city, hover.country].filter(Boolean).join(", ")} · ${hover.signins} sign-ins by ${hover.users} people${hover.failures ? ` · ${hover.failures} failed` : ""}` : "Hover a dot for details"}>
          {data.points.length ? (
            <div className="relative overflow-hidden rounded-lg bg-surface-2/50">
              <div className="absolute right-2 top-2 z-10 flex flex-col gap-1">
                {[
                  { label: "Zoom in", icon: Plus, run: () => setView((v) => ({ ...v, zoom: Math.min(16, v.zoom * 1.6) })) },
                  { label: "Zoom out", icon: Minus, run: () => setView((v) => ({ ...v, zoom: Math.max(1, v.zoom / 1.6) })) },
                  { label: "Reset view", icon: RotateCcw, run: () => setView(fitted) },
                ].map(({ label, icon: Icon, run }) => (
                  <button
                    key={label}
                    onClick={() => {
                      setUserMoved(label !== "Reset view");
                      run();
                    }}
                    aria-label={label}
                    title={label}
                    className="rounded-md border border-line bg-surface p-1.5 text-ink-2 shadow-sm hover:bg-surface-2"
                  >
                    <Icon size={14} aria-hidden />
                  </button>
                ))}
              </div>
              <ComposableMap projectionConfig={{ scale: 140 }} height={380} style={{ width: "100%", height: "auto" }}>
                <ZoomableGroup
                  center={view.center}
                  zoom={view.zoom}
                  minZoom={1}
                  maxZoom={16}
                  onMoveEnd={({ coordinates, zoom }: { coordinates: [number, number]; zoom: number }) => {
                    if (coordinates[0] !== view.center[0] || coordinates[1] !== view.center[1] || zoom !== view.zoom) {
                      setUserMoved(true);
                      setView({ center: coordinates, zoom });
                    }
                  }}
                >
                  <Geographies geography={world}>
                    {({ geographies }) =>
                      geographies.map((geo) => (
                        <Geography key={geo.rsmKey} geography={geo} fill={p["--border"]} stroke={p["--surface"]} strokeWidth={0.5 / view.zoom} style={{ default: { outline: "none" }, hover: { outline: "none" }, pressed: { outline: "none" } }} />
                      ))
                    }
                  </Geographies>
                  {data.points.map((pt, i) => (
                    <Marker key={i} coordinates={[pt.lon, pt.lat]} onMouseEnter={() => setHover(pt)} onMouseLeave={() => setHover(null)}>
                      {/* Divide by zoom so dots keep their on-screen size as the map zooms. */}
                      <circle
                        r={(4 + 10 * Math.sqrt(pt.signins / max)) / view.zoom}
                        fill={pt.failures ? p["--s2"] : p["--brand"]}
                        fillOpacity={0.75}
                        stroke={p["--surface"]}
                        strokeWidth={2 / view.zoom}
                      />
                    </Marker>
                  ))}
                </ZoomableGroup>
              </ComposableMap>
            </div>
          ) : (
            <Empty title={data.geoip ? "No located sign-ins yet" : "City database not installed"}>
              {data.geoip
                ? "Cities appear as sign-ins are synced and located."
                : "Run `python -m orgpulse.geoip_update` (the worker also does this on start) to plot cities. Countries are listed alongside."}
            </Empty>
          )}
          <p className="mt-2 flex flex-wrap gap-3 text-xs text-ink-3">
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: p["--brand"] }} /> sign-ins
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: p["--s2"] }} /> includes failed sign-ins
            </span>
            <span>Dot size = number of sign-ins</span>
            <a href="https://db-ip.com" target="_blank" rel="noreferrer" className="ml-auto hover:underline">
              IP Geolocation by DB-IP
            </a>
          </p>
        </Card>
        <Card title="By country">
          <BarList items={data.countries.map((c) => ({ key: c.country, label: c.country, value: c.signins, hint: `${c.users} people, ${c.failures} failed` }))} />
        </Card>
        <Card className="xl:col-span-3" title="New locations this week" subtitle="First successful sign-in from a country this user hasn't used before">
          <DataTable
            rows={data.new_locations}
            rowKey={(r) => `${r.user}-${r.country}`}
            empty="No new locations this week"
            columns={[
              { header: "User", cell: (r) => r.user },
              { header: "Country", cell: (r) => <Chip tone="serious">{r.country}</Chip> },
              { header: "First seen", cell: (r) => fmtDate(r.first_seen, true) },
            ]}
          />
        </Card>
      </div>
    </>
  );
}
