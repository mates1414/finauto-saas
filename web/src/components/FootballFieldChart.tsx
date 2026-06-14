import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface FootballFieldChartProps {
  currentPrice: number;
  dcfPrice: number;
  evEbitdaPrice: number;
  pePrice: number;
  evSalesPrice: number;
  currency?: string;
}

export const FootballFieldChart: React.FC<FootballFieldChartProps> = ({
  currentPrice,
  dcfPrice,
  evEbitdaPrice,
  pePrice,
  evSalesPrice,
  currency = "TRY",
}) => {
  // Generate valuation ranges centered around the target price
  // Usually, a +/- 15% range is standard for football fields
  const getRange = (price: number) => {
    if (!price) return [0, 0];
    return [price * 0.85, price * 1.15];
  };

  const dcfRange = getRange(dcfPrice);
  const evEbitdaRange = getRange(evEbitdaPrice);
  const peRange = getRange(pePrice);
  const evSalesRange = getRange(evSalesPrice);

  const data = [
    {
      name: "DCF Model",
      low: dcfRange[0],
      high: dcfRange[1],
      range: dcfRange,
      color: "#8B5CF6", // Purple
    },
    {
      name: "EV / EBITDA",
      low: evEbitdaRange[0],
      high: evEbitdaRange[1],
      range: evEbitdaRange,
      color: "#3B82F6", // Blue
    },
    {
      name: "P / E",
      low: peRange[0],
      high: peRange[1],
      range: peRange,
      color: "#10B981", // Green
    },
    {
      name: "EV / Sales",
      low: evSalesRange[0],
      high: evSalesRange[1],
      range: evSalesRange,
      color: "#F59E0B", // Amber
    },
  ].filter(item => item.low > 0); // Filter out any methodology with missing prices

  // Calculate X-axis bounds
  const allValues = [
    currentPrice,
    ...data.map((d) => d.low),
    ...data.map((d) => d.high),
  ].filter(Boolean);
  const minVal = allValues.length ? Math.min(...allValues) * 0.8 : 0;
  const maxVal = allValues.length ? Math.max(...allValues) * 1.2 : 500;

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const dataPoint = payload[0].payload;
      return (
        <div style={{
          backgroundColor: "rgba(17, 24, 39, 0.9)",
          border: "1px solid rgba(255, 255, 255, 0.15)",
          padding: "12px",
          borderRadius: "8px",
          color: "#fff",
          fontSize: "14px",
          boxShadow: "0 4px 12px rgba(0,0,0,0.5)"
        }}>
          <div style={{ fontWeight: 600, marginBottom: "4px" }}>{dataPoint.name}</div>
          <div>Low: <span style={{ color: "#9CA3AF" }}>{dataPoint.low.toFixed(2)} {currency}</span></div>
          <div>High: <span style={{ color: "#9CA3AF" }}>{dataPoint.high.toFixed(2)} {currency}</span></div>
        </div>
      );
    }
    return null;
  };

  return (
    <div style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 20, right: 30, left: 30, bottom: 20 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255, 255, 255, 0.05)" horizontal={false} />
          
          <XAxis
            type="number"
            domain={[Math.floor(minVal), Math.ceil(maxVal)]}
            stroke="rgba(255, 255, 255, 0.4)"
            style={{ fontSize: "12px" }}
            tickFormatter={(tick) => `${tick.toLocaleString()}`}
          />
          
          <YAxis
            type="category"
            dataKey="name"
            stroke="rgba(255, 255, 255, 0.6)"
            style={{ fontSize: "12px", fontWeight: 500 }}
            width={85}
          />
          
          <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(255, 255, 255, 0.02)" }} />
          
          {/* Render the floating bars */}
          <Bar dataKey="range" radius={4}>
            {data.map((entry, index) => (
              <Cell key={`cell-${index}`} fill={entry.color} fillOpacity={0.7} stroke={entry.color} strokeWidth={1} />
            ))}
          </Bar>

          {/* Reference line overlaying the current stock price */}
          {currentPrice && (
            <ReferenceLine
              x={currentPrice}
              stroke="#06B6D4"
              strokeWidth={2}
              strokeDasharray="4 4"
              label={{
                value: `Current: ${currentPrice.toFixed(2)} ${currency}`,
                fill: "#06B6D4",
                position: "top",
                fontSize: "12px",
                fontWeight: 600,
              }}
            />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};
