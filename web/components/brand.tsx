/**
 * The Org+ logo, loaded from web/public/brand/ (files kept exactly as supplied):
 *   logo-light.png  golden artwork, dark lettering: light theme
 *   logo-dark.png   teal artwork, white lettering:   dark theme
 * To change the logo, replace a file there. `crop` is the visible part of each file
 * (in its own pixels) so transparent margins don't shrink the logo; update it if a
 * replacement file has different margins.
 */
const LOGOS = {
  light: { src: "/brand/logo-light.png", width: 578, height: 220, crop: { x: 0, y: 0, w: 578, h: 220 } },
  dark: { src: "/brand/logo-dark.png", width: 2172, height: 724, crop: { x: 420, y: 76, w: 1334, h: 544 } },
} as const;

type Logo = (typeof LOGOS)[keyof typeof LOGOS];

/** Shows only the `crop` area of the image, scaled to the box (no file editing needed). */
function Cropped({ logo, alt, fill, height, className }: { logo: Logo; alt: string; fill: boolean; height?: number; className: string }) {
  const { crop } = logo;
  const ratio = crop.w / crop.h;
  return (
    <span
      className={`relative block overflow-hidden ${className}`}
      style={fill ? { width: "100%", aspectRatio: `${ratio}` } : { height, width: (height ?? 40) * ratio }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={logo.src}
        alt={alt}
        width={logo.width}
        height={logo.height}
        draggable={false}
        style={{
          position: "absolute",
          maxWidth: "none",
          width: `${(logo.width / crop.w) * 100}%`,
          height: "auto",
          left: `${(-crop.x / crop.w) * 100}%`,
          top: `${(-crop.y / crop.h) * 100}%`,
        }}
      />
    </span>
  );
}

export function BrandLogo({ height, fill = false }: { height?: number; fill?: boolean }) {
  return (
    <span className={fill ? "block w-full" : "inline-block"} role="img" aria-label="Org+">
      <Cropped logo={LOGOS.light} alt="" fill={fill} height={height} className="dark:hidden" />
      <Cropped logo={LOGOS.dark} alt="" fill={fill} height={height} className="hidden dark:block" />
    </span>
  );
}
