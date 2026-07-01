// Define SearchBar properties
interface SearchBarProps {

  // Search text
  value: string;

  // Function called when typing
  onChange: (value: string) => void;

}

// Search Bar component
function SearchBar({
  value,
  onChange,
}: SearchBarProps) {

  return (

    <input
      type="text"
      placeholder="Search molecular crystals..."
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="mb-8 w-full rounded-xl bg-[#111827] p-4 outline-none"
    />

  );

}

// Export component
export default SearchBar;