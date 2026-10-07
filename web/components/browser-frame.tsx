import Image from "next/image";

/**
 * A screenshot presented as product evidence: window chrome with the real
 * route in the address bar, then the captured frame itself. The chrome is
 * presentation only; the image is a capture of the running application.
 */
export function BrowserFrame({
  src,
  alt,
  route,
  priority = false,
}: {
  src: string;
  alt: string;
  route: string;
  priority?: boolean;
}) {
  return (
    <div className="border-border-strong bg-background-elevated overflow-hidden rounded-xl border shadow-[0_30px_80px_-30px_rgba(0,0,0,0.9)]">
      <div className="border-border bg-surface flex items-center gap-3 border-b px-4 py-2.5">
        <span aria-hidden="true" className="flex gap-1.5">
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
          <span className="bg-border-strong h-2.5 w-2.5 rounded-full" />
        </span>
        <span className="text-text-secondary bg-background border-border min-w-0 flex-1 truncate rounded-md border px-3 py-1 text-center font-mono text-xs">
          localhost:3000{route}
        </span>
        <span aria-hidden="true" className="w-10" />
      </div>
      <Image
        src={src}
        alt={alt}
        width={1440}
        height={900}
        priority={priority}
        sizes="(min-width: 1280px) 1100px, 100vw"
        className="block h-auto w-full"
      />
    </div>
  );
}
