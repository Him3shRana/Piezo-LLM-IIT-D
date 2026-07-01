// Import the ReactNode type for typing children
import type { ReactNode } from "react";

// Define the properties (props) our Button component accepts
interface ButtonProps {

  // Content displayed inside the button
  children: ReactNode;

  // Function executed when the button is clicked
  onClick?: () => void;

  // Additional Tailwind classes passed from outside
  className?: string;
}

// Create the reusable Button component
function Button({

  // Text, icons or other elements inside the button
  children,

  // Click event handler
  onClick,

  // Default empty class if none is provided
  className = "",

}: ButtonProps) {

  // Return the button UI
  return (

    // Main button element
    <button

      // Attach the click event
      onClick={onClick}

      // Apply default styles + custom styles
      className={`
        px-8
        py-3
        rounded-xl
        bg-blue-600
        text-white
        font-semibold
        shadow-lg
        cursor-pointer
        transition-all
        duration-300
        hover:scale-105
        hover:bg-blue-500
        active:scale-95
        ${className}
      `}
    >

      {/* Display whatever is passed between <Button>...</Button> */}
      {children}

    </button>
  );
}

// Make this component available for other files
export default Button;