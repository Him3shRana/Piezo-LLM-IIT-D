// Import ReactNode type
import type { ReactNode } from "react";

// Define the properties accepted by the Card component
interface CardProps {

  // Card title
  title: string;

  // Card value
  value: string;

  // Optional icon
  icon?: ReactNode;

}

// Card component
function Card({

  // Card title
  title,

  // Card value
  value,

  // Optional icon
  icon,

}: CardProps) {

  // Render card
  return (

    // Card container
    <div
      className="
        rounded-2xl
        border
        border-white/10
        bg-[#111827]
        p-6
        shadow-lg
        transition-all
        duration-300
        hover:-translate-y-1
        hover:border-cyan-400/40
        hover:shadow-cyan-500/20
      "
    >

      {/* Top section */}
      <div className="flex items-center justify-between">

        {/* Card title */}
        <h3 className="text-gray-400">

          {title}

        </h3>

        {/* Card icon */}
        <div>

          {icon}

        </div>

      </div>

      {/* Card value */}
      <h2 className="mt-6 text-4xl font-bold">

        {value}

      </h2>

    </div>

  );

}

// Export Card component
export default Card;