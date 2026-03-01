import { useMemo } from "react";
import { resolveSelectedAreaProfileTarget } from "../utils/selectedAreaProfileTarget";

export default function useSelectedAreaProfileTarget({ selectedFeatureProps, tractsActive }) {
  return useMemo(
    () => resolveSelectedAreaProfileTarget({ selectedFeatureProps, tractsActive }),
    [selectedFeatureProps, tractsActive]
  );
}
