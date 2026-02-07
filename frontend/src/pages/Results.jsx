import React from "react";
import ResultsDisplay from "../components/ResultsDisplay";

const Results = ({ result, error, loading }) => {
	return <ResultsDisplay result={result} error={error} loading={loading} />;
};

export default Results;
