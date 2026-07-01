// Import ReactNode type
import type { ReactNode } from "react";

// Define the properties accepted by the StatCard component
interface StatCardProps {

  // Card title
  title: string;

  // Main value
  value: string;

  // Icon displayed on the right
  icon: ReactNode;

  // Optional description
  description?: string;

}

// Dashboard statistics card
function StatCard({

  // Card title
  title,

  // Main value
  value,

  // Card icon
  icon,

  // Description
  description,

}: StatCardProps) {

  return (

    // Card container
    <div
      className="
        rounded-2xl
        border
        border-white/10
        bg-[#111827]
        p-6
        transition-all
        duration-300
        hover:-translate-y-1
        hover:border-cyan-400/40
      "
    >

      {/* Top row */}
      <div className="flex items-center justify-between">

        {/* Card title */}
        <p className="text-sm text-gray-400">

          {title}

        </p>

        {/* Card icon */}
        <div className="text-cyan-400">

          {icon}

        </div>

      </div>

      {/* Main value */}
      <h2 className="mt-4 text-3xl font-bold">

        {value}

      </h2>

      {/* Optional description */}
      {description && (

        <p className="mt-2 text-sm text-gray-500">

          {description}

        </p>

      )}

    </div>

  );

}

// Export component
export default StatCard;