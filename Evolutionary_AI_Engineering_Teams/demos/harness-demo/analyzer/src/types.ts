/** Shared types used by the analyzer + curator + Remotion video composition. */

export interface OcrBox {
  /** Verbatim string Apple Vision read. */
  text: string;
  /** 0-1 confidence. */
  conf: number;
  /** [x, y, w, h] in normalised image coords (origin lower-left). */
  box: [number, number, number, number];
}

export interface Keyframe {
  /** Sequential index in the keyframe extraction. */
  frame: number;
  /** Frame timestamp in the source video, in milliseconds. */
  tMs: number;
  /** OCR hits for this keyframe (may be empty if Apple Vision found nothing). */
  ocr: OcrBox[];
}

export interface FreezeRange {
  startMs: number;
  endMs: number;
  durationMs: number;
}

export interface SourceAnalysis {
  sourceId: string;
  /** Public-relative path of the source mp4 (relative to video/public). */
  publicPath: string;
  /** Source duration in seconds. */
  durationSec: number;
  /** Frame width × height after probing. */
  width: number;
  height: number;
  /** Keyframes extracted at the chosen sampling interval. */
  keyframes: Keyframe[];
  /** Stretches of the source where the picture stopped changing (Claude stalls etc.). */
  freezes: FreezeRange[];
}
