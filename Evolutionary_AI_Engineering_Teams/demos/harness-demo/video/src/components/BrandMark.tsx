import { CSSProperties } from 'react';

interface Props {
  size?: number;
  style?: CSSProperties;
}

/**
 * The product wordmark, rendered as styled text.
 *
 * CUSTOMISE: replace the spans below to match your product's brand.
 * The `.shimmer-text` class (in styles.css) applies a vertical white → pale
 * indigo gradient. Use it on the primary letters and add a coloured span on
 * any letter that has special significance (e.g. AIcG's lowercase 'c' is
 * fuchsia, GPT-4's '4' could be).
 *
 * Examples:
 *   "AIcG" — <span className="shimmer-text">AI</span><span style={{color:'#a855f7'}}>c</span><span className="shimmer-text">G</span>
 *   "Acme" — <span className="shimmer-text">Acme</span>
 */
export const BrandMark: React.FC<Props> = ({ size = 64, style }) => {
  return (
    <span
      style={{
        fontWeight: 900,
        letterSpacing: '-0.02em',
        fontSize: size,
        lineHeight: 1,
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      <span className="shimmer-text">PRODUCT</span>
    </span>
  );
};
