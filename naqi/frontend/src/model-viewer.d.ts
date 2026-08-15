import type { DetailedHTMLProps, HTMLAttributes } from "react";

declare global {
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
        src?: string;
        alt?: string;
        "camera-controls"?: string;
        "auto-rotate"?: string;
        autoplay?: string;
        exposure?: string;
        "shadow-intensity"?: string;
        "interaction-prompt"?: string;
      };
    }
  }
}

export {};
