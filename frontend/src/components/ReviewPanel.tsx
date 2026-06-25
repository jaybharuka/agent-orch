import React from "react";
import ReviewQueue from "./ReviewPanel/ReviewQueue";

const ReviewPanel: React.FC = () => {
  // In a real app this would come from auth context.
  const userId = process.env.REACT_APP_USER_ID || "user-1";
  return <ReviewQueue userId={userId} />;
};

export default ReviewPanel;
